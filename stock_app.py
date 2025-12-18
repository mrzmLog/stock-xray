import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np
import re

# -----------------------------------------------------------
# [1] 페이지 및 스타일 설정 (모바일 최적화 & 가독성)
# -----------------------------------------------------------
st.set_page_config(page_title="Info Nomad 적정주가 리포트", page_icon="📑", layout="wide")

st.markdown("""
<style>
    /* 전체 폰트 가독성 향상 */
    html, body, [class*="css"] {
        font-family: 'Pretendard', sans-serif;
        font-size: 1.05rem; /* 기본 폰트 키움 */
    }
    
    /* 제목 스타일 */
    h1 { font-size: 2.2rem !important; font-weight: 800 !important; color: #111; }
    h3 { font-size: 1.6rem !important; font-weight: 700 !important; margin-top: 30px !important; }
    h5 { font-size: 1.3rem !important; font-weight: 600 !important; color: #444; }

    /* 메트릭 카드 (모바일 반응형) */
    .metric-card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 15px;
        height: 100%; /* 높이 맞춤 */
    }
    .metric-label { font-size: 0.95rem; color: #666; margin-bottom: 5px; }
    .metric-value { font-size: 1.25rem; color: #000; font-weight: 800; }
    .metric-sub { font-size: 0.85rem; color: #888; margin-top: 5px; }

    /* 결과 박스 강조 */
    .result-box-success {
        background-color: #e6f9ed;
        border: 1px solid #b7ebc5;
        color: #1f7a38;
        padding: 15px;
        border-radius: 10px;
        font-weight: bold;
    }
    .result-box-warning {
        background-color: #fff8e6;
        border: 1px solid #ffeeba;
        color: #997404;
        padding: 15px;
        border-radius: 10px;
        font-weight: bold;
    }
    
    /* 팁 박스 */
    .tip-box {
        background-color: #f8f9fa;
        border-left: 4px solid #007bff;
        padding: 15px;
        margin-top: 10px;
        font-size: 0.95rem;
        color: #555;
    }
</style>
""", unsafe_allow_html=True)

st.title("📑 Info Nomad 적정주가 리포트")
st.caption("Annual Data Basis | Powered by Info Nomad")

# -----------------------------------------------------------
# [2] 기능: 분석 모델 설명
# -----------------------------------------------------------
with st.expander("📘 분석 모델 및 데이터 기준 설명 (열기)", expanded=False):
    st.markdown("""
    - **데이터 기준:** 네이버 금융의 **'최근 연간 실적'**만 사용합니다. (분기 제외)
    - **예상치(E):** 증권사 컨센서스가 있는 경우 미래 가치를 우선 반영합니다.
    - **S-RIM:** 자산(BPS) + 초과이익(ROE). (이익이 꾸준한 우량주용)
    - **벤저민 그레이엄:** 청산가치(BPS)와 수익가치(EPS)의 균형. (가치주용)
    - **피터 린치(PEG):** 이익 성장 속도(CAGR) 기반. (성장주용)
    """)

# -----------------------------------------------------------
# [3] 기능: 주식 리스트 및 데이터 크롤링
# -----------------------------------------------------------
@st.cache_data
def get_stock_list():
    df_krx = fdr.StockListing('KRX')
    df_krx['Search_Name'] = df_krx['Name'] + " (" + df_krx['Code'] + ")"
    return df_krx[['Search_Name', 'Code', 'Name']]

@st.cache_data(ttl=600) 
def get_stock_analysis(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        dfs = pd.read_html(response.text)
        
        financials = None
        for df in dfs:
            if '매출액' in str(df.iloc[:,0]) or '최근 연간 실적' in str(df.columns):
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        # 컬럼 정리
        if isinstance(financials.columns, pd.MultiIndex):
            new_columns = []
            drop_indices = []
            for i, col_tuple in enumerate(financials.columns):
                if any("분기" in str(x) for x in col_tuple):
                    drop_indices.append(i)
                    continue
                date_part = None
                for part in col_tuple:
                    if re.search(r'20\d{2}\.\d{2}', str(part)) or "(E)" in str(part):
                        date_part = part
                        break
                new_columns.append(date_part if date_part else "Descriptor")
            
            financials = financials.drop(financials.columns[drop_indices], axis=1)
            financials.columns = new_columns
        else:
            cols_to_drop = [c for c in financials.columns if "분기" in str(c)]
            financials = financials.drop(columns=cols_to_drop)

        if "Descriptor" in financials.columns:
            financials = financials.set_index("Descriptor")
        else:
            financials = financials.set_index(financials.columns[0])

        valid_cols = [c for c in financials.columns if re.search(r'20\d{2}\.\d{2}', str(c))]
        if not valid_cols:
            return None, f"연간 실적 식별 실패"
            
        financials = financials[valid_cols]
        target_col = valid_cols[-1] 
        is_estimate = "(E)" in target_col or "E" in target_col

        # 히스토리 데이터
        key_indices = ['매출액', '영업이익', '당기순이익', '영업이익률', '부채비율', 'ROE', 'EPS', 'BPS', 'PER', 'PBR']
        history_df = financials.loc[financials.index.str.contains('|'.join(key_indices), na=False)]
        
        # 값 추출 헬퍼
        def get_val(row_key, col_name):
            try:
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[col_name].iloc[0]
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
        
        # CAGR
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
# [4] 표 포맷팅 (단위 오류 수정: % 우선 적용)
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
                idx_clean = idx.replace(' ', '') 
                
                # 순서 중요: '율'이나 'ROE'가 있으면 먼저 % 처리
                if '율' in idx_clean or 'ROE' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:.2f} %"
                elif '매출액' in idx_clean or '영업이익' in idx_clean or '당기순이익' in idx_clean:
                     formatted_df.loc[idx, col] = f"{val_float:,.0f} 억"
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
# [5] 분석 인사이트 생성기 (자동 코멘트)
# -----------------------------------------------------------
def get_analysis_comment(model_name, fair_value, current_price, required_return=None):
    if fair_value <= 0:
        return "데이터 부족 또는 적자로 인해 계산할 수 없습니다."
    
    diff = (current_price - fair_value) / fair_value * 100
    
    if abs(diff) < 10:
        return "현재 주가는 적정가치와 비슷한 수준(**적정**)입니다."
    
    if diff > 0: # 고평가 (현재가가 더 비쌈)
        if model_name == "S-RIM":
            if required_return and required_return > 10:
                 return f"요구수익률({required_return}%)이 높아 적정가가 보수적으로 산출되었습니다."
            return "현재 주가에 **미래 성장 기대감(프리미엄)**이 반영되어 있습니다."
        elif model_name == "그레이엄":
            return "보수적인 청산가치 관점에서는 다소 **고평가** 상태입니다."
        else:
            return "펀더멘털 대비 주가가 높게 형성되어 있습니다."
            
    else: # 저평가 (현재가가 더 쌈)
        if diff < -30:
            return "기업 가치 대비 **현저한 저평가** 구간입니다. (안전마진 확보)"
        return "적정 가치보다 **저렴한** 상태입니다."

# -----------------------------------------------------------
# [UI] 사이드바 및 메인
# -----------------------------------------------------------
st.sidebar.header("🔍 종목 검색")
try:
    with st.spinner("리스트 로딩..."):
        stock_list = get_stock_list()
    selected_stock = st.sidebar.selectbox(
        "종목 선택", stock_list['Search_Name'], index=None, placeholder="종목명 입력"
    )
except:
    st.sidebar.error("로딩 실패")
    selected_stock = None

st.sidebar.divider()
st.sidebar.header("🎛 S-RIM 설정")
srim_option = st.sidebar.radio(
    "요구수익률(k):", ("BBB- 회사채 (8.0%)", "한국주식 평균 (10.0%)", "국채 금리 (4.0%)", "직접 입력"), index=0
)
if "8.0%" in srim_option: default_k = 8.0
elif "10.0%" in srim_option: default_k = 10.0
elif "4.0%" in srim_option: default_k = 4.0
else: default_k = 8.0
required_return = st.sidebar.slider("상세 조정 (%)", 2.0, 20.0, default_k, 0.1)

if selected_stock:
    code = selected_stock.split('(')[-1].replace(')', '')
    stock_name = selected_stock.split('(')[0]

    with st.spinner(f"'{stock_name}' 연간 실적 분석 중..."):
        data, error = get_stock_analysis(code)

    if error:
        st.error(error)
    elif data:
        # 계산
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

        # [섹션 1] 실적 표 (모바일 대응: dataframe 사용)
        st.markdown("##### 1️⃣ 최근 연간 실적 흐름")
        st.caption("※ 모바일에서는 표를 좌우로 밀어서 확인하세요.")
        display_df = format_financial_table(data['history_df'])
        
        # st.table 대신 st.dataframe 사용 (반응형 스크롤 지원)
        st.dataframe(display_df, use_container_width=True)
        
        if data['is_estimate']:
            st.info(f"💡 **참고:** '{data['target_year']}' 데이터는 증권사 **예상치(Consensus)**입니다.")

        st.divider()

        # [섹션 2] 적정주가 리포트
        st.markdown(f"##### 2️⃣ 적정주가 산출 리포트 (기준: {data['target_year']})")
        
        # 공통 스타일 함수
        def draw_report_card(title, inputs, result_value, formula, comment):
            with st.container():
                st.markdown(f"**{title}**")
                c1, c2 = st.columns([1, 1.2]) # 모바일에서도 적절한 비율
                
                with c1:
                    input_html = "".join([f"<div>• {k}: <b>{v}</b></div>" for k, v in inputs.items()])
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">입력 데이터</div>
                        {input_html}
                    </div>
                    """, unsafe_allow_html=True)
                
                with c2:
                    res_cls = "result-box-success" if "저평가" in comment or "저렴" in comment else "result-box-warning"
                    if result_value <= 0: res_cls = "result-box-warning"
                    
                    val_str = f"{result_value:,.0f}원" if result_value > 0 else "계산 불가"
                    
                    st.markdown(f"""
                    <div class="{res_cls}">
                        <div style="font-size:0.9rem; color:#555;">적정주가</div>
                        <div style="font-size:1.4rem;">{val_str}</div>
                    </div>
                    <div class="tip-box">
                        <b>🤖 분석 의견:</b><br>{comment}
                    </div>
                    """, unsafe_allow_html=True)
                    
                with st.expander("수식 보기"):
                    st.latex(formula)
                st.write("") # 간격

        # S-RIM 출력
        srim_inputs = {
            "BPS": f"{data['bps']:,.0f}원",
            "ROE": f"{data['roe']}%",
            "요구수익률": f"{required_return}%"
        }
        srim_comment = get_analysis_comment("S-RIM", srim, data['price'], required_return)
        draw_report_card("① S-RIM (사경인 모델)", srim_inputs, srim, 
                         r"BPS + \frac{BPS \times (ROE - k)}{k}", srim_comment)

        # 그레이엄 출력
        graham_inputs = {
            "EPS": f"{data['eps']:,.0f}원",
            "BPS": f"{data['bps']:,.0f}원",
            "상수": "22.5"
        }
        graham_comment = get_analysis_comment("그레이엄", graham, data['price'])
        draw_report_card("② 벤저민 그레이엄 (NCAV)", graham_inputs, graham, 
                         r"\sqrt{22.5 \times EPS \times BPS}", graham_comment)

        # 피터 린치 출력
        lynch_inputs = {
            "EPS": f"{data['eps']:,.0f}원",
            "성장률": f"{data['eps_growth']:.1f}%",
            "비고": "Max 30% 제한"
        }
        lynch_comment = get_analysis_comment("PEG", peter_lynch, data['price'])
        draw_report_card("③ 피터 린치 (PEG)", lynch_inputs, peter_lynch, 
                         r"EPS \times Growth Rate", lynch_comment)

        st.divider()

        # [섹션 3] 최종 요약
        st.markdown("##### 3️⃣ 최종 결론")
        summary = pd.DataFrame({
            "모델": ["현재 주가", "S-RIM", "그레이엄", "피터 린치"],
            "가격": [data['price'], srim if srim > 0 else 0, graham if graham > 0 else 0, peter_lynch if peter_lynch > 0 else 0]
        })
        
        # 차트용
        chart_data = summary[summary['가격'] > 0].set_index("모델")
        
        c_left, c_right = st.columns([1, 1])
        with c_left:
             # 테이블용 포맷팅
            summary_disp = summary.copy()
            summary_disp['가격'] = summary_disp['가격'].apply(lambda x: f"{x:,.0f}원" if x > 0 else "-")
            st.dataframe(summary_disp, hide_index=True, use_container_width=True)
        with c_right:
            st.bar_chart(chart_data)

else:
    st.info("👈 왼쪽 사이드바에서 종목을 검색해주세요.")
