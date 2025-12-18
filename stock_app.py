import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np

# -----------------------------------------------------------
# 페이지 설정
# -----------------------------------------------------------
st.set_page_config(page_title="Info Nomad 적정주가 리포트", page_icon="📑", layout="wide")

# 스타일 커스텀 (깔끔한 보고서 느낌)
st.markdown("""
<style>
    .metric-card {
        background-color: #f9f9f9;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
    }
    .big-font {
        font-size: 1.2rem !important;
        font-weight: 600;
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
    - **데이터 기준:** 네이버 금융의 **'최근 연간 실적'**을 사용합니다. (분기 데이터 미사용)
    - **예상치(E) 활용:** 증권사 컨센서스(예상치)가 있는 경우, 미래 가치를 반영하기 위해 우선 사용합니다.
    - **S-RIM:** 자산가치(BPS) + 초과이익가치(ROE). (우량주용)
    - **벤저민 그레이엄:** BPS와 EPS의 기하평균. (가치주용)
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
# [기능 3] 데이터 크롤링 (연간 데이터 전용)
# -----------------------------------------------------------
@st.cache_data(ttl=600) 
def get_stock_analysis(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        dfs = pd.read_html(response.text)
        
        financials = None
        # '최근 연간 실적' 테이블 찾기 (보통 첫번째가 연간, 두번째가 분기)
        # 확실하게 하기 위해 컬럼과 인덱스를 검사
        for df in dfs:
            # 네이버 금융 테이블 특징: 첫번째 컬럼에 '매출액' 등이 포함됨
            if '매출액' in str(df.iloc[:,0]) or '최근 연간 실적' in str(df.columns):
                # 분기가 아닌 연간인지 확인 (컬럼명에 .12 등이 많은지)
                # 네이버는 보통 상단 테이블이 연간임.
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        # 데이터 클렌징
        financials = financials.set_index(financials.columns[0])
        
        # 컬럼 정리 (날짜가 있는 컬럼만 필터링: "2021.12", "2024.12(E)" 등)
        # 네이버 테이블 구조상 불필요한 컬럼이 섞일 수 있음
        valid_cols = [c for c in financials.columns if '20' in str(c) and ('.12' in str(c) or '(E)' in str(c))]
        
        if not valid_cols:
            return None, "연간 실적 컬럼을 식별할 수 없습니다."
            
        financials = financials[valid_cols] # 유효한 연간 컬럼만 남김

        # ---------------------------------------------------
        # 1. 기준 연도(Target Year) 선정
        # ---------------------------------------------------
        # 가장 최근 데이터 (맨 오른쪽) 사용. (E)가 있으면 그것 사용.
        target_col = valid_cols[-1] 
        is_estimate = "(E)" in target_col # 예상치 여부

        # ---------------------------------------------------
        # 2. 3개년 히스토리 데이터 추출 (표시용)
        # ---------------------------------------------------
        # 주요 지표만 뽑아서 Transpose
        key_indices = ['매출액', '영업이익', '당기순이익', '부채비율', 'ROE', 'EPS', 'BPS', 'PER', 'PBR']
        history_df = financials.loc[financials.index.str.contains('|'.join(key_indices), na=False)]
        
        # ---------------------------------------------------
        # 3. 계산용 데이터 추출 (Target Year 기준)
        # ---------------------------------------------------
        def get_val(row_key):
            try:
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[target_col].iloc[0]
                if pd.isna(val): # 해당 연도 데이터 없으면 전년도 시도
                     val = row[valid_cols[-2]].iloc[0]
                return float(str(val).replace(',', ''))
            except:
                return 0

        roe = get_val('ROE')
        eps = get_val('EPS')
        bps = get_val('BPS')
        per = get_val('PER')
        revenue = get_val('매출액')
        op_income = get_val('영업이익')
        
        # ---------------------------------------------------
        # 4. 성장률 (CAGR) 계산
        # ---------------------------------------------------
        eps_growth_rate = 0
        try:
            # 3년 전 데이터 찾기 (없으면 있는 것 중 가장 오래된 것)
            start_col = valid_cols[0] 
            # 연수 차이 계산 (2024 - 2021 = 3년)
            start_year = int(start_col[:4])
            end_year = int(target_col[:4])
            years = end_year - start_year
            
            if years > 0:
                row_eps = financials.loc[financials.index.str.contains('EPS', na=False)]
                eps_start = float(str(row_eps[start_col].iloc[0]).replace(',', ''))
                eps_end = float(str(row_eps[target_col].iloc[0]).replace(',', ''))
                
                # 적자에서 흑자전환 등은 CAGR 계산 왜곡되므로 제외
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
            "revenue": revenue,
            "op_income": op_income,
            "eps_growth": eps_growth_rate,
            "target_year": target_col, # 계산에 사용된 기준 연도 이름
            "is_estimate": is_estimate,
            "history_df": history_df # 3개년 표 데이터
        }, None

    except Exception as e:
        return None, f"오류 발생: {str(e)}"

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
    elif data:
        # ---------------------------------------------------
        # 계산 로직
        # ---------------------------------------------------
        # 1. S-RIM
        srim = 0
        if data['bps'] > 0:
            excess_return_value = data['bps'] * (data['roe'] - required_return) / 100 
            srim = data['bps'] + (excess_return_value / (required_return / 100))

        # 2. 그레이엄
        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5
            
        # 3. 피터 린치
        peter_lynch = 0
        growth_cap = min(data['eps_growth'], 30) # 성장률 Cap
        peg_ratio = 0
        if data['eps'] > 0 and growth_cap > 0:
            peter_lynch = data['eps'] * growth_cap
            if data['per'] > 0:
                peg_ratio = data['per'] / data['eps_growth']

        # ---------------------------------------------------
        # UI: 헤더 정보
        # ---------------------------------------------------
        st.subheader(f"🏢 {stock_name} ({data['code']})")
        st.write(f"현재 주가: **{data['price']:,.0f}원**")
        st.divider()

        # ---------------------------------------------------
        # [섹션 1] 연간 실적 히스토리 (요청사항 반영)
        # ---------------------------------------------------
        st.markdown("##### 1️⃣ 최근 3~4년 연간 실적 추이")
        st.caption("※ 네이버 금융 '최근 연간 실적' 기준 (단위: 억 원, 원, %, 배)")
        
        # DataFrame 표시 (깔끔하게)
        st.dataframe(data['history_df'], use_container_width=True)
        
        if data['is_estimate']:
            st.info(f"💡 **알림:** **'{data['target_year']}'** 데이터는 증권사 **예상치(Consensus)**를 포함하고 있습니다.")

        st.divider()

        # ---------------------------------------------------
        # [섹션 2] 적정주가 산출 (기준 시점 명시)
        # ---------------------------------------------------
        st.markdown(f"##### 2️⃣ 적정주가 산출 리포트 (기준: {data['target_year']})")
        
        # 2-1. S-RIM
        with st.container():
            st.markdown(f"**① S-RIM (사경인 모델)**")
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <small>입력 데이터 ({data['target_year']})</small><br>
                    - <b>BPS:</b> {data['bps']:,.0f}원<br>
                    - <b>ROE:</b> {data['roe']}%<br>
                    - <b>요구수익률:</b> {required_return}%
                </div>
                """, unsafe_allow_html=True)
            with col2:
                valuation = "N/A"
                if srim > 0:
                    diff = (data['price'] - srim) / srim * 100
                    valuation = f"**{srim:,.0f}원** ({diff:+.1f}%)"
                st.success(f"👉 적정가: {valuation}")
                st.caption(f"산출식: BPS + (BPS x (ROE - {required_return}%)) / {required_return}%")

        # 2-2. 그레이엄
        with st.container():
            st.write("") # 여백
            st.markdown(f"**② 벤저민 그레이엄 (NCAV)**")
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <small>입력 데이터 ({data['target_year']})</small><br>
                    - <b>EPS:</b> {data['eps']:,.0f}원<br>
                    - <b>BPS:</b> {data['bps']:,.0f}원
                </div>
                """, unsafe_allow_html=True)
            with col2:
                valuation = f"**{graham:,.0f}원**" if graham > 0 else "계산 불가 (적자)"
                st.success(f"👉 적정가: {valuation}")
                st.caption("산출식: √(22.5 x EPS x BPS)")

        # 2-3. 피터 린치
        with st.container():
            st.write("")
            st.markdown(f"**③ 피터 린치 (PEG)**")
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <small>입력 데이터</small><br>
                    - <b>EPS ({data['target_year']}):</b> {data['eps']:,.0f}원<br>
                    - <b>성장률(CAGR):</b> {data['eps_growth']:.1f}%
                </div>
                """, unsafe_allow_html=True)
            with col2:
                valuation = f"**{peter_lynch:,.0f}원**" if peter_lynch > 0 else "계산 불가 (성장 정체)"
                st.success(f"👉 적정가: {valuation}")
                st.caption("산출식: EPS x 성장률 (성장률 Max 30% 제한 적용)")

        st.divider()

        # ---------------------------------------------------
        # [섹션 3] 최종 요약
        # ---------------------------------------------------
        st.markdown("##### 3️⃣ 최종 결론")
        
        summary = pd.DataFrame({
            "모델": ["현재 주가", "S-RIM", "그레이엄", "피터 린치"],
            "적정 주가": [
                data['price'], 
                srim if srim > 0 else 0, 
                graham if graham > 0 else 0, 
                peter_lynch if peter_lynch > 0 else 0
            ]
        })
        
        # 차트용 데이터 (0 제거)
        chart_data = summary[summary['적정 주가'] > 0].set_index("모델")
        
        c_left, c_right = st.columns([1, 1])
        with c_left:
            st.table(summary.style.format({"적정 주가": "{:,.0f}원"}))
        with c_right:
            st.bar_chart(chart_data)

else:
    st.info("👈 왼쪽 사이드바에서 종목을 검색해주세요.")
