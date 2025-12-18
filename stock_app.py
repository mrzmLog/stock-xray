import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np

# -----------------------------------------------------------
# 페이지 설정
# -----------------------------------------------------------
st.set_page_config(page_title="적정주가 분석기 ver 2.0", page_icon="📊", layout="wide")

st.title("📊 적정주가 분석 리포트")
st.caption("Last Update: 2025.12 | Powered by Info Nomad")

# -----------------------------------------------------------
# [기능 1] 분석 모델 설명 (야마구치 삭제)
# -----------------------------------------------------------
with st.expander("📘 분석 모델 참조 사항 (열기)", expanded=False):
    st.markdown("""
    - **S-RIM:** 기업의 자산(BPS)과 초과이익(ROE)을 기반으로 합니다. (제조/금융/우량주 적합)
    - **벤저민 그레이엄:** 청산가치(BPS)와 수익가치(EPS)의 기하평균입니다. (가치주 적합)
    - **피터 린치 (PEG):** 이익성장률(Growth) 대비 주가수익비율(PER)을 봅니다. (성장주 적합)
    """)

# -----------------------------------------------------------
# [기능 2] 주식 리스트 (검색용)
# -----------------------------------------------------------
@st.cache_data
def get_stock_list():
    df_krx = fdr.StockListing('KRX')
    df_krx['Search_Name'] = df_krx['Name'] + " (" + df_krx['Code'] + ")"
    return df_krx[['Search_Name', 'Code', 'Name']]

# -----------------------------------------------------------
# [기능 3] 데이터 크롤링 (핵심 로직 유지)
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
            if '최근 연간 실적' in str(df.columns) or '매출액' in str(df.iloc[:,0]):
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        financials = financials.set_index(financials.columns[0])
        target_col = financials.columns[-2] # 확정 실적

        def get_val(row_key):
            try:
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[target_col].iloc[0]
                if pd.isna(val):
                     val = row[financials.columns[-3]].iloc[0]
                return float(str(val).replace(',', ''))
            except:
                return 0

        # 데이터 추출
        roe = get_val('ROE')
        eps = get_val('EPS')
        bps = get_val('BPS')
        per = get_val('PER')
        pbr = get_val('PBR')
        revenue = get_val('매출액')
        op_income = get_val('영업이익')
        debt_ratio = get_val('부채비율')
        
        # EPS 성장률 (3년 전 대비)
        eps_growth_rate = 0
        try:
            row_eps = financials.loc[financials.index.str.contains('EPS', na=False)]
            eps_old = float(str(row_eps.iloc[0, -4]).replace(',', ''))
            eps_curr = float(str(row_eps.iloc[0, -2]).replace(',', ''))
            if eps_old > 0 and eps_curr > 0:
                eps_growth_rate = ((eps_curr / eps_old) ** (1/2) - 1) * 100
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
            "pbr": pbr,
            "revenue": revenue,
            "op_income": op_income,
            "debt_ratio": debt_ratio,
            "eps_growth": eps_growth_rate,
            "target_year": target_col
        }, None

    except Exception as e:
        return None, f"오류 발생: {str(e)}"

# -----------------------------------------------------------
# 사이드바 설정 (종목 검색 & S-RIM 옵션)
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
st.sidebar.header("🎛 S-RIM 입력값 설정")
srim_option = st.sidebar.radio(
    "요구수익률(k) 기준:",
    ("BBB- 회사채 (8.0%)", "한국주식 평균 (10.0%)", "국채 금리 (4.0%)", "직접 입력"),
    index=0
)

if "8.0%" in srim_option: default_k = 8.0
elif "10.0%" in srim_option: default_k = 10.0
elif "4.0%" in srim_option: default_k = 4.0
else: default_k = 8.0

required_return = st.sidebar.slider("요구수익률(%) 상세 조정", 2.0, 20.0, default_k, 0.1)

# -----------------------------------------------------------
# 메인 분석 로직
# -----------------------------------------------------------
if selected_stock:
    code = selected_stock.split('(')[-1].replace(')', '')
    stock_name = selected_stock.split('(')[0]

    with st.spinner(f"'{stock_name}' 정밀 분석 중..."):
        data, error = get_stock_analysis(code)

    if error:
        st.error(error)
    elif data:
        # 모델 계산
        # 1. 그레이엄
        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5
            
        # 2. S-RIM
        srim = 0
        if data['bps'] > 0:
            excess_return_value = data['bps'] * (data['roe'] - required_return) / 100 
            srim = data['bps'] + (excess_return_value / (required_return / 100))

        # 3. 피터 린치
        peter_lynch = 0
        peg_ratio = 0
        growth_cap = min(data['eps_growth'], 50) 
        if data['eps'] > 0 and growth_cap > 0:
            peter_lynch = data['eps'] * growth_cap 
            if data['per'] > 0:
                peg_ratio = data['per'] / data['eps_growth']

        # ---------------------------------------------------
        # [섹션 1] 종합 기초 데이터 (요청사항: 기본지표 + 재무제표 항목 통합)
        # ---------------------------------------------------
        st.subheader(f"📌 {stock_name} 기초 펀더멘털")
        
        # 주요 지표 1행
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("현재 주가", f"{data['price']:,.0f}원")
        c2.metric("PER (주가수익비율)", f"{data['per']}배")
        c3.metric("PBR (주가순자산비율)", f"{data['pbr']}배")
        c4.metric("ROE (자기자본이익률)", f"{data['roe']}%")
        c5.metric("EPS 성장률(2년)", f"{data['eps_growth']:.1f}%")

        # 재무 데이터 테이블 (DataFrame 활용)
        st.markdown("###### 📋 핵심 재무 데이터 (단위: 억 원, 원, %)")
        fin_df = pd.DataFrame({
            "구분": ["매출액", "영업이익", "부채비율", "EPS(주당순이익)", "BPS(주당순자산)"],
            "값": [
                f"{data['revenue']:,.0f}억", 
                f"{data['op_income']:,.0f}억", 
                f"{data['debt_ratio']}%",
                f"{data['eps']:,.0f}원", 
                f"{data['bps']:,.0f}원"
            ]
        }).set_index("구분").transpose() # 가로로 길게 보기 위해 전치
        st.table(fin_df)

        st.divider()

        # ---------------------------------------------------
        # [섹션 2] 모델별 상세 입력값 및 산출 근거 (차트 삭제, 계산식 복원)
        # ---------------------------------------------------
        st.subheader("🧮 적정주가 산출 상세 근거")

        # 1. S-RIM
        st.markdown("#### 1. S-RIM (사경인 모델)")
        col_s1, col_s2 = st.columns([1, 2])
        with col_s1:
            st.info("**입력 데이터 (Input)**")
            st.write(f"- **자산가치(BPS):** {data['bps']:,.0f}원")
            st.write(f"- **수익가치(ROE):** {data['roe']}%")
            st.write(f"- **요구수익률(k):** {required_return}%")
        with col_s2:
            st.success(f"**산출 결과: {srim:,.0f}원**")
            st.markdown("**계산 공식:**")
            st.latex(r"적정주가 = BPS + \frac{BPS \times (ROE - k)}{k}")
            if srim <= 0: st.caption("※ ROE가 요구수익률보다 현저히 낮아 계산 불가")

        st.markdown("---")

        # 2. 벤저민 그레이엄
        st.markdown("#### 2. 벤저민 그레이엄 모델")
        col_g1, col_g2 = st.columns([1, 2])
        with col_g1:
            st.info("**입력 데이터 (Input)**")
            st.write(f"- **EPS (주당순이익):** {data['eps']:,.0f}원")
            st.write(f"- **BPS (주당순자산):** {data['bps']:,.0f}원")
            st.write(f"- **상수:** 22.5 (PER 15 x PBR 1.5)")
        with col_g2:
            st.success(f"**산출 결과: {graham:,.0f}원**")
            st.markdown("**계산 공식:**")
            st.latex(r"적정주가 = \sqrt{22.5 \times EPS \times BPS}")
            if graham <= 0: st.caption("※ EPS가 적자이므로 계산 불가")

        st.markdown("---")

        # 3. 피터 린치 (PEG)
        st.markdown("#### 3. 피터 린치 (PEG) 모델")
        col_p1, col_p2 = st.columns([1, 2])
        with col_p1:
            st.info("**입력 데이터 (Input)**")
            st.write(f"- **EPS:** {data['eps']:,.0f}원")
            st.write(f"- **성장률(G):** {growth_cap:.1f}% (최대 50% 제한)")
            st.write(f"- **현재 PER:** {data['per']}배")
        with col_p2:
            st.success(f"**산출 결과: {peter_lynch:,.0f}원**")
            st.markdown("**계산 공식:**")
            st.latex(r"적정주가 = EPS \times Growth Rate")
            st.markdown(f"**PEG 지수:** {peg_ratio:.2f} (0.5 이하 저평가)")
            if peter_lynch <= 0: st.caption("※ 성장률이 없거나 마이너스라 계산 불가")

        st.divider()

        # ---------------------------------------------------
        # [섹션 3] 최종 결과 요약 표
        # ---------------------------------------------------
        st.subheader("🏆 최종 분석 요약")
        
        summary_data = {
            "모델명": ["현재 시장가", "S-RIM (수익가치)", "벤저민 그레이엄 (보수적)", "피터 린치 (성장성)"],
            "적정 주가": [
                f"{data['price']:,.0f}원", 
                f"{srim:,.0f}원" if srim > 0 else "계산 불가",
                f"{graham:,.0f}원" if graham > 0 else "계산 불가",
                f"{peter_lynch:,.0f}원" if peter_lynch > 0 else "계산 불가"
            ],
            "현재가 대비": [
                "-",
                f"{(data['price'] - srim)/srim*100:+.1f}%" if srim > 0 else "-",
                f"{(data['price'] - graham)/graham*100:+.1f}%" if graham > 0 else "-",
                f"{(data['price'] - peter_lynch)/peter_lynch*100:+.1f}%" if peter_lynch > 0 else "-"
            ],
            "비고": [
                "Real Time",
                f"요구수익률 {required_return}% 기준",
                "EPS x BPS 기반",
                f"성장률 {growth_cap:.1f}% 반영"
            ]
        }
        st.table(pd.DataFrame(summary_data))

else:
    st.info("👈 왼쪽 사이드바에서 분석할 종목을 검색해주세요.")
