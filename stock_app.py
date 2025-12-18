import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np

# -----------------------------------------------------------
# 페이지 설정 및 제목 (요청사항 반영)
# -----------------------------------------------------------
st.set_page_config(page_title="적정주가 분석기 ver 1.0", page_icon="📈", layout="wide")

st.title("📈 적정주가 분석기 ver 1.0")
st.caption("Last Update: 2025년 12월 | Powered by Info Nomad")

# -----------------------------------------------------------
# [기능 1] 분석 모델 및 섹터 설명 (요청사항 반영)
# -----------------------------------------------------------
with st.expander("📘 분석 모델 설명 및 적용 섹터 가이드 (필독)", expanded=False):
    st.markdown("""
    ### 1. S-RIM (사경인 회계사 모델)
    - **원리:** 기업의 자기자본(BPS)에 초과이익(ROE)을 더해 가치를 평가합니다.
    - **적용 대상:** **제조업, 금융업, 일반 우량주** (이익이 꾸준한 기업).
    - **비추천:** 바이오, 적자 기업, 변동성이 극심한 기업.

    ### 2. 벤저민 그레이엄 모델 (NCAV)
    - **원리:** "망해도 남는 돈"을 계산합니다. 보수적인 청산가치 중심.
    - **적용 대상:** **자산주, 지주사, 전통 가치주** (저PBR).
    - **비추천:** IT, 플랫폼, 서비스업 (무형자산 비중이 높은 기업).

    ### 3. 피터 린치 PEG 모델 (신규)
    - **원리:** "성장하는 만큼 PER를 부여한다". (PER / 성장률)
    - **적용 대상:** **반도체, 2차전지, 엔터, 소프트웨어** 등 고성장주.
    - **핵심:** PEG가 1.0 이하면 저평가, 0.5 이하면 강력 매수.

    ### 4. 야마구치 요헤이 모델 (신규)
    - **원리:** (영업이익 × 10) + (유동자산 - 부채). 회사의 현금 창출력 중시.
    - **적용 대상:** **중소형 가치주, 현금부자 기업**.
    - **특징:** 회계적으로 매우 직관적이고 현실적인 적정가 산출.
    """)

# -----------------------------------------------------------
# [기능 2] 한국 주식 목록 가져오기 (종목명 검색용)
# -----------------------------------------------------------
@st.cache_data
def get_stock_list():
    # KRX 전체 상장 종목 가져오기 (속도를 위해 캐싱)
    df_krx = fdr.StockListing('KRX')
    # 종목명과 코드만 추출해서 문자열로 결합 "삼성전자 (005930)"
    df_krx['Search_Name'] = df_krx['Name'] + " (" + df_krx['Code'] + ")"
    return df_krx[['Search_Name', 'Code', 'Name']]

# -----------------------------------------------------------
# [핵심] 데이터 크롤링 및 분석 함수 (기존 로직 유지 + 신규 모델 추가)
# -----------------------------------------------------------
@st.cache_data(ttl=600) 
def get_stock_analysis(code):
    try:
        # 1. 네이버 금융 메인
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        
        # 2. 파싱
        dfs = pd.read_html(response.text)
        
        financials = None
        for df in dfs:
            if '최근 연간 실적' in str(df.columns) or '매출액' in str(df.iloc[:,0]):
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        financials = financials.set_index(financials.columns[0])
        target_col = financials.columns[-2] # 확정 실적 (보통 뒤에서 두번째)

        # 데이터 추출 헬퍼
        def get_val(row_key):
            try:
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[target_col].iloc[0]
                if pd.isna(val): # 확정치 없으면 전년도
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
        op_income = get_val('영업이익') # 영업이익
        debt_ratio = get_val('부채비율')
        
        # PEG 계산을 위한 EPS 성장률 추정 (최근 3년 데이터 활용)
        eps_growth_rate = 0
        try:
            row_eps = financials.loc[financials.index.str.contains('EPS', na=False)]
            # 3년전 EPS와 현재 EPS 비교 (단순 연평균 성장률)
            eps_old = float(str(row_eps.iloc[0, -4]).replace(',', '')) # 3년전
            eps_curr = float(str(row_eps.iloc[0, -2]).replace(',', '')) # 현재
            if eps_old > 0 and eps_curr > 0:
                # 2년 기간 동안의 성장률
                eps_growth_rate = ((eps_curr / eps_old) ** (1/2) - 1) * 100
        except:
            eps_growth_rate = 0 # 계산 불가시 0

        # 야마구치 모델용 유동자산/부채 (간이 계산을 위해 BPS 활용 역산)
        # 정확한 유동자산은 상세 페이지 가야하므로, 여기선 BPS * 주식수 등으로 자본 총계 추정하거나
        # 네이버 요약 테이블의 한계로 인해 약식 로직 사용: (영업이익 * 10) + (순자산 * 0.5 [보수적])
        # *제대로 하려면 상세 재무제표가 필요하지만, 속도를 위해 약식 적용*
        
        # 3. 현재가
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
# [기능 3] 종목 검색 UI (텍스트 입력 -> 선택 방식)
# -----------------------------------------------------------
st.sidebar.header("🔍 종목 검색")
try:
    with st.spinner("종목 리스트를 불러오는 중..."):
        stock_list = get_stock_list()
        
    # 검색창 (Selectbox)
    selected_stock = st.sidebar.selectbox(
        "종목을 선택하거나 입력하세요", 
        stock_list['Search_Name'],
        index=None,
        placeholder="예: 삼성전자"
    )
except:
    st.sidebar.error("종목 목록 로딩 실패. 새로고침 해주세요.")
    selected_stock = None

# -----------------------------------------------------------
# [기능 4] S-RIM 요구수익률 옵션 (Presets)
# -----------------------------------------------------------
st.sidebar.divider()
st.sidebar.header("🎛 S-RIM 설정")

# 라디오 버튼으로 프리셋 선택
srim_option = st.sidebar.radio(
    "요구수익률 기준 선택:",
    ("BBB- 회사채 (8.0%)", "한국주식 평균 (10.0%)", "국채/예금 금리 (4.0%)", "직접 입력"),
    index=0
)

# 선택에 따른 값 설정
if "8.0%" in srim_option:
    default_k = 8.0
elif "10.0%" in srim_option:
    default_k = 10.0
elif "4.0%" in srim_option:
    default_k = 4.0
else:
    default_k = 8.0 # 직접 입력 시 기본값

# 슬라이더 (값 조절 가능)
required_return = st.sidebar.slider(
    "요구수익률(%) 상세 조절", 
    min_value=2.0, max_value=20.0, value=default_k, step=0.1
)

st.sidebar.info(f"현재 적용된 요구수익률: **{required_return}%**")


# -----------------------------------------------------------
# 메인 로직 실행
# -----------------------------------------------------------
if selected_stock:
    # "삼성전자 (005930)" -> "005930" 추출
    code = selected_stock.split('(')[-1].replace(')', '')
    stock_name = selected_stock.split('(')[0]

    with st.spinner(f"'{stock_name}' 재무 데이터 분석 중..."):
        data, error = get_stock_analysis(code)

    if error:
        st.error(error)
    elif data:
        # ---------------------------------------------------
        # [분석] 4가지 모델 계산
        # ---------------------------------------------------
        
        # 1. 그레이엄 (보수적)
        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5

        # 2. S-RIM (사용자 요구수익률 반영)
        srim = 0
        if data['bps'] > 0:
            excess_return_value = data['bps'] * (data['roe'] - required_return) / 100 
            srim = data['bps'] + (excess_return_value / (required_return / 100))

        # 3. 피터 린치 (PEG) - 성장주용
        # 적정주가 = EPS * EPS성장률 * 100 (PEG=1 기준)
        # 단, 성장률이 너무 높으면 왜곡되므로 최대 30%로 제한하거나, PER 배수 적용
        peter_lynch = 0
        peg_ratio = 0
        if data['eps'] > 0 and data['eps_growth'] > 0:
            # 피터린치 식: 적정 PER = 성장률
            # 적정 주가 = EPS * 성장률
            # (보수적으로 성장률 최대 50% 제한)
            growth_cap = min(data['eps_growth'], 50) 
            peter_lynch = data['eps'] * growth_cap 
            if data['per'] > 0:
                peg_ratio = data['per'] / data['eps_growth']

        # 4. 야마구치 (약식) - 영업이익 기반
        # 적정주가 = (영업이익 * 10 + 순자산) / 유통주식수
        # *여기서는 주식수를 모르므로, 주당 지표로 변환해서 계산*
        # 주당 영업이익(OpEPS) 추정 = EPS * (영업이익/당기순이익) -> 약식으로 EPS * 1.2 배 등으로 가정하거나
        # 그냥 간단하게: BPS(순자산) + (EPS * 10) [영업가치 10배]
        yamaguchi = 0
        if data['eps'] > 0:
            # 영업가치(수익가치)를 EPS의 10배로 가정 + 자산가치(BPS)
            # 순수 야마구치 모델보다는 '수익+자산 복합 모델'에 가까움
            yamaguchi = (data['eps'] * 10) + data['bps']

        # ---------------------------------------------------
        # [결과] UI 출력
        # ---------------------------------------------------
        st.divider()
        st.header(f"📊 {stock_name} ({code}) 분석 결과")
        
        # 상단 핵심 지표
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("현재 주가", f"{data['price']:,.0f}원")
        c2.metric("ROE", f"{data['roe']}%")
        c3.metric("PER", f"{data['per']}배")
        c4.metric("PBR", f"{data['pbr']}배")
        c5.metric("EPS 성장률", f"{data['eps_growth']:.1f}%")

        # 탭 메뉴 구성
        tab1, tab2, tab3 = st.tabs(["🏆 종합 적정주가", "📝 모델별 상세 근거", "📋 재무제표"])

        # [Tab 1] 종합 차트
        with tab1:
            st.subheader("4대 모델 적정주가 비교")
            
            # 차트 데이터 생성
            chart_data = {
                "구분": ["현재 주가", "S-RIM", "그레이엄", "피터린치(성장)", "야마구치(복합)"],
                "가격": [data['price'], srim, graham, peter_lynch, yamaguchi]
            }
            df_chart = pd.DataFrame(chart_data)
            df_chart = df_chart[df_chart['가격'] > 0] # 0이하 제외

            st.bar_chart(df_chart.set_index("구분"), use_container_width=True)
            
            # 간단 코멘트
            st.info(f"""
            - **S-RIM ({required_return}% 적용):** {srim:,.0f}원
            - **그레이엄 (가치주):** {graham:,.0f}원
            - **피터 린치 (성장주):** {peter_lynch:,.0f}원 (성장률 {min(data['eps_growth'], 50):.1f}% 반영)
            - **야마구치 (자산+수익):** {yamaguchi:,.0f}원
            """)

        # [Tab 2] 상세 근거
        with tab2:
            st.markdown("#### 1. S-RIM (사경인 모델)")
            st.write(f"설정된 요구수익률 **{required_return}%** 대비 초과이익을 계산합니다.")
            if srim > 0:
                diff = (data['price'] - srim) / srim * 100
                st.write(f"👉 적정가: **{srim:,.0f}원** (현재가 대비 {diff:.1f}% {'비쌈' if diff > 0 else '저렴'})")
            else:
                st.warning("ROE가 낮아 계산 불가")
            st.divider()

            st.markdown("#### 2. 벤저민 그레이엄")
            st.write("EPS와 BPS를 기반으로 한 전통적 가치평가입니다.")
            st.latex(r"\sqrt{22.5 \times EPS \times BPS}")
            st.write(f"👉 적정가: **{graham:,.0f}원**")
            st.divider()

            st.markdown("#### 3. 피터 린치 (PEG)")
            st.write("성장률(Growth)을 PER로 치환하여 가치를 매깁니다.")
            st.write(f"- 최근 EPS 성장률: **{data['eps_growth']:.1f}%**")
            if peg_ratio > 0:
                st.write(f"- 현재 PEG (PER/성장률): **{peg_ratio:.2f}** (0.5 이하면 매력적)")
            st.write(f"👉 적정가: **{peter_lynch:,.0f}원**")
            st.caption("* 성장률이 마이너스거나 없으면 계산되지 않습니다.")
            st.divider()

            st.markdown("#### 4. 야마구치 (약식)")
            st.write("기업의 자산(BPS)에 10년치 수익(EPS x 10)을 더한 본질 가치입니다.")
            st.write(f"👉 적정가: **{yamaguchi:,.0f}원**")

        # [Tab 3] 재무제표
        with tab3:
            st.dataframe(pd.DataFrame({
                "지표": ["매출액", "영업이익", "부채비율", "ROE", "EPS", "BPS"],
                "값": [
                    f"{data['revenue']:,.0f}억", f"{data['op_income']:,.0f}억", 
                    f"{data['debt_ratio']}%", f"{data['roe']}%", 
                    f"{data['eps']:,.0f}원", f"{data['bps']:,.0f}원"
                ]
            }))
            st.caption(f"데이터 기준: {data['target_year']} (네이버 금융)")

else:
    st.info("👈 왼쪽 사이드바에서 **종목을 검색**해주세요.")
