import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np
import re

# -----------------------------------------------------------
# 페이지 설정
# -----------------------------------------------------------
st.set_page_config(page_title="Info Nomad 적정주가 리포트", page_icon="📑", layout="wide")

st.markdown("""
<style>
    /* 가독성 강화 스타일 */
    .big-font { font-size: 1.1rem !important; }
    .metric-card {
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #dee2e6;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
    .metric-label { font-size: 0.9rem; color: #6c757d; font-weight: 600; }
    .metric-value { font-size: 1.1rem; color: #212529; font-weight: 700; }
    thead tr th {
        background-color: #e9ecef !important;
        font-weight: bold !important;
        color: #495057 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📑 Info Nomad 적정주가 리포트")
st.caption("Annual Data Basis | Powered by Info Nomad")

# -----------------------------------------------------------
# [기능 1] 모델 설명
# -----------------------------------------------------------
with st.expander("📘 분석 모델 및 데이터 기준 설명 (열기)", expanded=False):
    st.markdown("""
    - **데이터 기준:** 네이버 금융의 **'최근 연간 실적'**만 사용합니다. (분기 데이터 자동 제외)
    - **예상치(E) 활용:** 증권사 컨센서스(예상치)가 있는 경우 미래 가치를 우선 반영합니다.
    - **S-RIM:** 자산가치(BPS) + 초과이익가치(ROE). (이익이 꾸준한 우량주용)
    - **벤저민 그레이엄:** BPS와 EPS의 기하평균. (자산가치 중시)
    - **피터 린치 (PEG):** 연간 EPS 성장률(CAGR) 기반. (성장주용)
    """)

# -----------------------------------------------------------
# [기능 2] 주식 리스트
# -----------------------------------------------------------
@st.cache_data
def get_stock_list():
    df_krx = fdr.StockListing('KRX')
    df_krx['Search_Name'] = df_krx['Name'] + " (" + df_krx['Code'] + ")"
    return df_krx[['Search_Name', 'Code', 'Name']]

# -----------------------------------------------------------
# [기능 3] 데이터 크롤링 (지능형 컬럼 파싱 적용)
# -----------------------------------------------------------
@st.cache_data(ttl=600) 
def get_stock_analysis(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        dfs = pd.read_html(response.text)
        
        financials = None
        for df in dfs:
            # '최근 연간 실적' 혹은 '매출액'이 포함된 메인 재무제표 찾기
            if '매출액' in str(df.iloc[:,0]) or '최근 연간 실적' in str(df.columns):
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        # ---------------------------------------------------
        # [핵심 로직] MultiIndex 컬럼 지능형 정리
        # ---------------------------------------------------
        if isinstance(financials.columns, pd.MultiIndex):
            new_columns = []
            drop_indices = []
            
            for i, col_tuple in enumerate(financials.columns):
                # 1. '분기'가 포함된 컬럼은 무조건 삭제 리스트에 추가
                if any("분기" in str(x) for x in col_tuple):
                    drop_indices.append(i)
                    continue
                
                # 2. 날짜(YYYY.MM) 혹은 (E)가 있는 부분을 찾아 헤더로 사용
                date_part = None
                for part in col_tuple:
                    if re.search(r'20\d{2}\.\d{2}', str(part)) or "(E)" in str(part):
                        date_part = part
                        break
                
                if date_part:
                    new_columns.append(date_part)
                else:
                    # 날짜가 없으면 라벨 컬럼(주요재무정보 등)으로 간주
                    new_columns.append("Descriptor")
            
            # 분기 데이터 삭제
            financials = financials.drop(financials.columns[drop_indices], axis=1)
            # 새 컬럼명 적용
            financials.columns = new_columns
        
        else:
            # 단일 인덱스일 경우도 '분기' 포함 컬럼 삭제
            cols_to_drop = [c for c in financials.columns if "분기" in str(c)]
            financials = financials.drop(columns=cols_to_drop)

        # ---------------------------------------------------
        # 데이터 정제
        # ---------------------------------------------------
        # 첫 번째 컬럼을 인덱스로 설정 (주요재무정보)
        if "Descriptor" in financials.columns:
            financials = financials.set_index("Descriptor")
        else:
            financials = financials.set_index(financials.columns[0])

        # 유효한 연간 컬럼만 필터링 (날짜 패턴이 있는 것만)
        valid_cols = [c for c in financials.columns if re.search(r'20\d{2}\.\d{2}', str(c))]
        
        if not valid_cols:
            return None, f"연간 실적 데이터를 식별할 수 없습니다. (헤더 파싱 실패)"
            
        financials = financials[valid_cols]

        # ---------------------------------------------------
        # 기준 연도(Target Year) 선정
        # ---------------------------------------------------
        target_col = valid_cols[-1] 
        is_estimate = "(E)" in target_col or "E" in target_col

        # ---------------------------------------------------
        # 히스토리 데이터 추출
        # ---------------------------------------------------
        key_indices = ['매출액', '영업이익', '당기순이익', '영업이익률', '부채비율', 'ROE', 'EPS', 'BPS', 'PER', 'PBR']
        history_df = financials.loc[financials.index.str.contains('|'.join(key_indices), na=False)]
        
        # ---------------------------------------------------
        # 값 추출 함수 (결측치 처리 강화)
        # ---------------------------------------------------
        def get_val(row_key, col_name):
            try:
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[col_name].iloc[0]
                
                # 데이터가 없거나 '-' 인 경우 직전 연도 데이터 사용 시도
                if pd.isna(val) or str(val).strip() in ['-', '', 'nan']:
                    prev_idx = valid_cols.index(col_name) - 1
                    if prev_idx >= 0:
                        val = row[valid_cols[prev_idx]].iloc[0]
                
                return float(str(val).replace(',', ''))
            except:
                return 0

        roe = get_val('ROE', target_col)
        eps = get_val('EPS', target_col)
        bps = get_val('BPS', target_col)
        per = get_val('PER', target_col)
        
        # ---------------------------------------------------
        # 성장률 (CAGR) 계산
        # ---------------------------------------------------
        eps_growth_rate = 0
        try:
            start_col = valid_cols[0]
            start_year = int(re.search(r'20\d{2}', str(start_col)).group())
            end_year = int(re.search(r'20\d{2}', str(target_col)).group())
            years = end_year - start_year
            
            if years > 0:
                eps_start = get_val('EPS', start_col)
                eps_end = get_val('EPS', target_col)
                if eps_start > 0 and eps_end > 0:
                    eps_growth_rate = ((eps_end / eps_start) ** (1/years) - 1) * 100
        except:
            eps_growth_rate = 0

        # 현재가
        df_price = fdr.DataReader(code)
        if df_price.empty: return None, "주가 정보 오류"
        current_price = df_price['Close'].iloc[-1]
        
        return {
            "code": code,
            "price": current_price,
            "roe": roe,
            "eps": eps,
            "bps": bps,
            "per": per,
            "eps_growth": eps_growth_rate,
            "target_year": target_col,
            "is_estimate": is_estimate,
            "history_df": history_df
        }, None

    except Exception as e:
        return None, f"오류 발생: {str(e)}"

# -----------------------------------------------------------
# [UI Helper] 표 포맷팅 (단위 적용)
# -----------------------------------------------------------
def format_financial_table(df):
    formatted_df = df.copy()
    for col in formatted_df.columns:
        for idx in formatted_df.index:
            try:
                val = formatted_df.loc[idx, col]
                if pd.isna(val) or str(val).strip() in ['-', '', 'nan']:
                    formatted_df.loc[idx, col] = "-"
                    continue
                
                val_float = float(str(val).replace(',', ''))
                
                # 인덱스 이름(idx)을 기준으로 단위 적용
                idx_clean = idx.replace(' ', '') # 공백 제거 후 비교
                
                if '매출액' in idx_clean or '영업이익' in idx_clean or '당기순이익' in idx_clean:
                    if '율' not in idx_clean: # 영업이익률 제외
                        formatted_df.loc[idx, col] = f"{val_float:,.0f} 억"
                    else:
                        formatted_df.loc[idx, col] = f"{val_float:.2f} %"
                elif '율' in idx_clean or 'ROE' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:.2f} %"
                elif 'EPS' in idx_clean or 'BPS' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:,.0f} 원"
                elif 'PER' in idx_clean or 'PBR' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:.2f} 배"
                else:
                    formatted_df.loc[idx, col] = f"{val_float:,.2f}"
            except:
                continue
    return formatted_df

# -----------------------------------------------------------
# 사이드바
# -----------------------------------------------------------
st.sidebar.header("🔍 종목 검색")
try:
    with st.spinner("리스트 로딩 중..."):
        stock_list = get_stock_list()
    selected_stock = st.sidebar.selectbox(
        "종목 선택", stock_list['Search_Name'], index=None, placeholder="종목명 입력"
    )
except:
    st.sidebar.error("목록 로딩 실패")
    selected_stock = None

st.sidebar.divider()
st.sidebar.header("🎛 S-RIM 설정")
srim_option = st.sidebar.radio(
    "요구수익률(k):",
    ("BBB- 회사채 (8.0%)", "한국주식 평균 (10.0%)", "국채 금리 (4.0%)", "직접 입력"),
    index=0
)
if "8.0%" in srim_option: default_k = 8.0
elif "10.0%" in srim_option: default_k = 10.0
elif "4.0%" in srim_option: default_k = 4.0
else: default_k = 8.0
required_return = st.sidebar.slider("상세 조정 (%)", 2.0, 20.0, default_k, 0.1)

# -----------------------------------------------------------
# 메인 로직
# -----------------------------------------------------------
if selected_stock:
    code = selected_stock.split('(')[-1].replace(')', '')
    stock_name = selected_stock.split('(')[0]

    with st.spinner(f"'{stock_name}' 연간 실적 데이터 분석 중..."):
        data, error = get_stock_analysis(code)

    if error:
        st.error(error)
        st.info("💡 팁: 최근 상장주이거나 ETF/ETN 종목은 재무제표 형식이 달라 분석이 어려울 수 있습니다.")
    elif data:
        # 계산 로직
        srim = 0
        if data['bps'] > 0:
            excess_return_value = data['bps'] * (data['roe'] - required_return) / 100 
            srim = data['bps'] + (excess_return_value / (required_return / 100))

        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5
            
        peter_lynch = 0
        growth_cap = min(data['eps_growth'], 30)
        if data['eps'] > 0 and growth_cap > 0:
            peter_lynch = data['eps'] * growth_cap

        # UI 출력
        st.subheader(f"🏢 {stock_name} ({data['code']})")
        st.markdown(f"#### 현재 주가: :blue[{data['price']:,.0f}원]")
        st.divider()

        # 섹션 1
        st.markdown("##### 1️⃣ 최근 연간 실적 흐름")
        display_df = format_financial_table(data['history_df'])
        st.table(display_df)
        if data['is_estimate']:
            st.caption(f"※ '{data['target_year']}' 데이터는 증권사 예상치(Consensus)입니다.")

        st.divider()

        # 섹션 2
        st.markdown(f"##### 2️⃣ 적정주가 산출 리포트 (기준: {data['target_year']})")
        
        # S-RIM
        with st.container():
            st.markdown(f"**① S-RIM (사경인 모델)**")
            col1, col2 = st.columns([1, 1.5])
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">입력 데이터</div>
                    <div>• BPS: <b>{data['bps']:,.0f}원</b></div>
                    <div>• ROE: <b>{data['roe']}%</b></div>
                    <div>• 요구수익률: <b>{required_return}%</b></div>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                valuation = f"{srim:,.0f}원" if srim > 0 else "N/A"
                diff_text = f"({(data['price'] - srim)/srim*100:+.1f}%)" if srim > 0 else ""
                st.success(f"👉 적정주가: **{valuation}** {diff_text}")
                st.info(f"산출식: $BPS + \\frac{{BPS \\times (ROE - {required_return}\\%)}}{{{required_return}\\%}}$")

        # 그레이엄
        with st.container():
            st.markdown(f"**② 벤저민 그레이엄 (NCAV)**")
            col1, col2 = st.columns([1, 1.5])
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">입력 데이터</div>
                    <div>• EPS: <b>{data['eps']:,.0f}원</b></div>
                    <div>• BPS: <b>{data['bps']:,.0f}원</b></div>
                    <div>• 상수: <b>22.5</b></div>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                valuation = f"{graham:,.0f}원" if graham > 0 else "계산 불가"
                st.success(f"👉 적정주가: **{valuation}**")
                st.info(r"산출식: $\sqrt{22.5 \times EPS \times BPS}$")

        # 피터 린치
        with st.container():
            st.markdown(f"**③ 피터 린치 (PEG)**")
            col1, col2 = st.columns([1, 1.5])
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">입력 데이터</div>
                    <div>• EPS: <b>{data['eps']:,.0f}원</b></div>
                    <div>• 성장률: <b>{data['eps_growth']:.1f}%</b></div>
                    <div style="color:#999; font-size:0.8em;">(Max 30% 제한)</div>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                valuation = f"{peter_lynch:,.0f}원" if peter_lynch > 0 else "계산 불가"
                st.success(f"👉 적정주가: **{valuation}**")
                st.info(r"산출식: $EPS \times Growth Rate$")

        st.divider()

        # 섹션 3
        st.markdown("##### 3️⃣ 최종 결론")
        summary = pd.DataFrame({
            "모델": ["현재 주가", "S-RIM", "그레이엄", "피터 린치"],
            "적정 주가": [data['price'], srim if srim > 0 else 0, graham if graham > 0 else 0, peter_lynch if peter_lynch > 0 else 0]
        })
        chart_data = summary[summary['적정 주가'] > 0].set_index("모델")
        
        c_left, c_right = st.columns([1, 1.5])
        with c_left:
            summary_display = summary.copy()
            summary_display['적정 주가'] = summary_display['적정 주가'].apply(lambda x: f"{x:,.0f}원" if x > 0 else "-")
            st.table(summary_display)
        with c_right:
            st.bar_chart(chart_data)

else:
    st.info("👈 왼쪽 사이드바에서 종목을 검색해주세요.")
