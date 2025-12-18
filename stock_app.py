import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np

# -----------------------------------------------------------
# 페이지 설정
# -----------------------------------------------------------
st.set_page_config(page_title="Info Nomad 한국주식 분석기", page_icon="🇰🇷", layout="wide")

# 스타일 커스텀 (표 헤더 색상 등)
st.markdown("""
<style>
    th {background-color: #f0f2f6 !important;}
    div[data-testid="stMetricValue"] {font-size: 1.2rem;}
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------
# [함수] 데이터 가져오기 (네이버 금융 상세 크롤링)
# -----------------------------------------------------------
@st.cache_data(ttl=600) 
def get_stock_analysis(code):
    try:
        # 1. 네이버 금융 메인 페이지
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        
        # 2. 데이터 파싱
        dfs = pd.read_html(response.text)
        
        # 재무제표 테이블 찾기
        financials = None
        for df in dfs:
            if '최근 연간 실적' in str(df.columns) or '매출액' in str(df.iloc[:,0]):
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        # 데이터 정리 (인덱스 설정)
        financials = financials.set_index(financials.columns[0])
        
        # 최신 결산 데이터 위치 찾기 (보통 뒤에서 두 번째가 확정 실적)
        # 안전하게 데이터가 있는 가장 최근 컬럼을 찾음
        target_col = financials.columns[-2] 

        # -------------------------------------------------------
        # 데이터 추출 헬퍼 함수
        # -------------------------------------------------------
        def get_val(row_key):
            try:
                # 행 이름에 row_key가 포함된 줄 찾기
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[target_col].iloc[0]
                
                # 결측치면 그 앞해 데이터 사용
                if pd.isna(val):
                     val = row[financials.columns[-3]].iloc[0]
                
                return float(str(val).replace(',', ''))
            except:
                return 0

        # 핵심 지표 추출
        roe = get_val('ROE')
        eps = get_val('EPS')
        bps = get_val('BPS')
        per = get_val('PER')
        pbr = get_val('PBR')
        revenue = get_val('매출액')
        operating_income = get_val('영업이익')
        debt_ratio = get_val('부채비율')

        # 3. 현재가 및 종목명 (FDR 사용)
        df_price = fdr.DataReader(code)
        if df_price.empty: return None, "주가 정보 오류"
        current_price = df_price['Close'].iloc[-1]
        
        # 종목명은 네이버 페이지 타이틀 등에서 가져올 수도 있으나, 
        # 여기서는 FDR의 목록을 쓰거나 간단히 처리. (속도를 위해 생략)
        
        return {
            "code": code,
            "price": current_price,
            "roe": roe,
            "eps": eps,
            "bps": bps,
            "per": per,
            "pbr": pbr,
            "revenue": revenue,
            "op_income": operating_income,
            "debt_ratio": debt_ratio,
            "target_year": target_col  # 기준 년도
        }, None

    except Exception as e:
        return None, f"분석 중 오류 발생: {str(e)}"

# -----------------------------------------------------------
# [UI] 화면 구성
# -----------------------------------------------------------
st.title("🇰🇷 Info Nomad 주식 분석기")
st.markdown("##### :blue[재무제표 기반] 적정주가 산출 및 상세 리포트")

# 입력창
with st.expander("🔍 종목코드 검색 가이드 (열기/닫기)", expanded=False):
    st.info("티커 대신 **6자리 숫자 코드**를 입력하세요. (예: 삼성전자 005930, 카카오 035720)")

code = st.text_input("종목코드 (6자리) 입력:", placeholder="005930", max_chars=6)

if code and len(code) == 6:
    with st.spinner('재무 데이터와 주가를 분석하고 있습니다...'):
        data, error = get_stock_analysis(code)

    if error:
        st.error(error)
    elif data:
        # -------------------------------------------------------
        # 계산 로직
        # -------------------------------------------------------
        # 1. 그레이엄 모델
        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5
            
        # 2. S-RIM (요구수익률 8% 가정)
        required_return = 8.0 # %
        srim = 0
        excess_return = 0
        if data['bps'] > 0:
            # ROE가 요구수익률보다 낮으면 할인됨
            srim = data['bps'] + (data['bps'] * (data['roe'] - required_return) / required_return)

        # -------------------------------------------------------
        # 결과 화면 (Tabs 구성)
        # -------------------------------------------------------
        st.divider()
        st.header(f"📈 분석 결과 (기준: {data['target_year']})")
        
        # 상단 핵심 요약
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("현재 주가", f"{data['price']:,.0f}원")
        col2.metric("종합 의견", "저평가" if data['price'] < srim else "고평가" if srim > 0 else "판단보류", 
                    delta=f"{((data['price']-srim)/srim*100):.1f}% 괴리율" if srim > 0 else None,
                    delta_color="inverse")
        col3.metric("ROE (자기자본이익률)", f"{data['roe']}%")
        col4.metric("PER (주가수익비율)", f"{data['per']}배")

        # 탭 메뉴
        tab1, tab2, tab3 = st.tabs(["📊 적정주가 차트", "📝 산출 근거 (해설)", "📋 주요 재무제표"])

        # [Tab 1] 차트 및 결론
        with tab1:
            st.subheader("적정주가 밴드")
            chart_df = pd.DataFrame({
                "구분": ["현재 주가", "그레이엄 가치", "S-RIM 가치"],
                "금액": [data['price'], graham, srim]
            })
            # 0 이하 값은 차트에서 제외
            chart_df = chart_df[chart_df['금액'] > 0]
            
            st.bar_chart(chart_df.set_index("구분"), use_container_width=True)
            
            st.info(f"""
            **💡 분석 요약**
            - 현재 주가는 **{data['price']:,.0f}원**입니다.
            - 기업의 자산가치와 수익성을 고려한 S-RIM 적정가는 **{srim:,.0f}원**입니다.
            - 벤저민 그레이엄 모델에 따른 내재가치는 **{graham:,.0f}원**입니다.
            """)

        # [Tab 2] 산출 근거 (상세 설명)
        with tab2:
            st.subheader("🧐 적정주가는 어떻게 계산되었나요?")
            
            st.markdown("#### 1. S-RIM (사경인 회계사 방식)")
            st.write("기업의 자기자본(BPS)에 초과이익(ROE)을 더해 가치를 평가합니다.")
            st.latex(r"적정주가 = BPS + \left( BPS \times \frac{ROE - 요구수익률}{요구수익률} \right)")
            
            st.markdown(f"""
            - **BPS (주당순자산):** {data['bps']:,.0f}원
            - **ROE (자기자본이익률):** {data['roe']}%
            - **요구수익률:** {required_return}% (일반적인 주식투자 기대수익률)
            """)
            
            if srim > 0:
                st.success(f"🧮 **계산 결과:** {data['bps']:,.0f} + ({data['bps']:,.0f} × ({data['roe']} - {required_return}) / {required_return}) = **{srim:,.0f}원**")
            else:
                st.warning("ROE가 요구수익률보다 현저히 낮거나 적자 상태여서 S-RIM 계산값이 음수가 나옵니다.")

            st.markdown("---")

            st.markdown("#### 2. 벤저민 그레이엄 모델")
            st.write("가치투자의 창시자 그레이엄의 보수적인 평가 공식입니다.")
            st.latex(r"적정주가 = \sqrt{22.5 \times EPS \times BPS}")
            
            st.markdown(f"""
            - **EPS (주당순이익):** {data['eps']:,.0f}원 (기업이 1주당 번 돈)
            - **BPS (주당순자산):** {data['bps']:,.0f}원 (기업이 망하면 주주가 받는 돈)
            """)
            
            if graham > 0:
                st.success(f"🧮 **계산 결과:** √ (22.5 × {data['eps']:,.0f} × {data['bps']:,.0f}) = **{graham:,.0f}원**")
            else:
                st.warning("EPS(이익)가 적자여서 그레이엄 모델을 적용할 수 없습니다.")

        # [Tab 3] 주요 재무제표
        with tab3:
            st.subheader("📋 핵심 재무 지표 (단위: 억 원, %, 배)")
            
            # 보기 좋게 데이터프레임 생성
            fin_data = {
                "지표 명": ["매출액", "영업이익", "부채비율", "ROE", "EPS", "BPS", "PER", "PBR"],
                "값": [
                    f"{data['revenue']:,.0f} 억",
                    f"{data['op_income']:,.0f} 억",
                    f"{data['debt_ratio']}%",
                    f"{data['roe']}%",
                    f"{data['eps']:,.0f} 원",
                    f"{data['bps']:,.0f} 원",
                    f"{data['per']} 배",
                    f"{data['pbr']} 배"
                ]
            }
            st.table(pd.DataFrame(fin_data).set_index("지표 명"))
            st.caption(f"* 데이터 출처: 네이버 금융 (기준: {data['target_year']})")
