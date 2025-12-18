import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests

# -----------------------------------------------------------
# 페이지 설정
# -----------------------------------------------------------
st.set_page_config(page_title="Info Nomad 한국주식 분석기", page_icon="🇰🇷", layout="wide")

# -----------------------------------------------------------
# [함수] 네이버 금융 크롤링 (재무 데이터)
# -----------------------------------------------------------
@st.cache_data(ttl=600) 
def get_naver_stock_info(code):
    try:
        # 1. 네이버 금융 메인 페이지 접속
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        
        # 봇 탐지 방지용 헤더
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers)
        
        # 2. pandas로 HTML 내의 표(Table) 읽기
        dfs = pd.read_html(response.text)
        
        # 3. 데이터 추출 (네이버 페이지 구조에 맞춰 파싱)
        # 통상적으로 '주요재무제표'는 3번째 혹은 4번째 테이블에 있음
        financials = None
        for df in dfs:
            if '최근 연간 실적' in str(df.columns) or '매출액' in str(df.iloc[:,0]):
                financials = df
                break
        
        if financials is None:
            return None, "재무제표 테이블을 찾을 수 없습니다."

        # 데이터 정리 (최근 결산 기준 - 보통 맨 오른쪽이 최신 추정치거나 작년 확정치)
        # 네이버 금융 표 구조: [매출액, 영업이익, ..., ROE, PER, BPS, EPS ...]
        financials = financials.set_index(financials.columns[0])
        
        # 최근 4분기 혹은 작년 확정치 가져오기 (빗금/Null 처리)
        # 안전하게 뒤에서 두번째 열(최근 확정 실적)을 가져오는 로직
        target_col_index = -1 
        
        # 필요한 지표 추출 함수
        def get_value(row_name):
            try:
                # 행 이름이 포함된 줄을 찾음
                row_data = financials.loc[financials.index.str.contains(row_name, na=False)]
                if row_data.empty: return 0
                
                # 값 추출 (문자열 등 처리)
                val = row_data.iloc[0, target_col_index]
                if pd.isna(val): # 최신 예측치가 없으면 전년도 데이터 사용
                    val = row_data.iloc[0, target_col_index - 1]
                    
                return float(str(val).replace(',', ''))
            except:
                return 0

        roe = get_value('ROE')
        eps = get_value('EPS')
        bps = get_value('BPS')
        per = get_value('PER')
        pbr = get_value('PBR')
        
        # 현재가 가져오기 (FDR 이용)
        df_price = fdr.DataReader(code)
        if df_price.empty:
            return None, "주가 정보를 가져올 수 없습니다."
        current_price = df_price['Close'].iloc[-1]
        
        # 종목명은 별도로 가져오거나 사용자 입력 신뢰
        # 여기서는 편의상 코드 그대로 사용하거나 별도 API 필요하지만, 
        # KRX 목록을 미리 받아두는건 무거우므로 생략하고 진행
        
        return {
            "price": current_price,
            "roe": roe,
            "eps": eps,
            "bps": bps,
            "per": per,
            "pbr": pbr
        }, None

    except Exception as e:
        return None, f"네이버 접속 중 오류: {str(e)}"

# -----------------------------------------------------------
# [UI] 화면 구성
# -----------------------------------------------------------
st.title("🇰🇷 한국주식 적정주가 분석기 (Naver 기반)")
st.caption("네이버 금융 데이터를 기반으로 S-RIM과 그레이엄 모델을 분석합니다.")

with st.expander("🔍 사용법 (티커 대신 숫자 코드만 입력하세요)", expanded=True):
    st.write("""
    - **입력 방법:** 종목코드 6자리를 입력하세요.
    - **삼성전자:** `005930`
    - **에코프로비엠:** `247540`
    - **카카오:** `035720`
    """)

code = st.text_input("종목코드 입력 (6자리):", placeholder="예: 005930")

if code and len(code) == 6:
    with st.spinner('네이버 금융에서 데이터를 가져오는 중...'):
        data, error = get_naver_stock_info(code)

    if error:
        st.error(f"⚠️ {error}")
    elif data:
        # 계산 로직
        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5
            
        srim = 0
        req_return = 0.08 # 요구수익률 8%
        if data['roe'] and data['bps'] > 0:
            srim = data['bps'] * (data['roe'] / 100 / req_return) # ROE가 10.5 형태라서 100 나눔

        # 결과 표시
        st.divider()
        st.subheader(f"📊 종목코드 {code} 분석 결과")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재 주가", f"{data['price']:,.0f}원")
        c2.metric("ROE", f"{data['roe']}%")
        c3.metric("EPS", f"{data['eps']:,.0f}원")
        c4.metric("BPS", f"{data['bps']:,.0f}원")
        
        st.divider()
        
        # 차트
        chart_df = pd.DataFrame({
            "모델": ["현재 주가", "그레이엄 적정가", "S-RIM 적정가"],
            "가격": [data['price'], graham, srim]
        })
        chart_df = chart_df[chart_df['가격'] > 0]
        
        st.bar_chart(chart_df.set_index("모델"))
        
        # 코멘트
        st.subheader("💡 투자 포인트")
        if srim > 0:
            diff = (data['price'] - srim) / srim * 100
            if diff < 0:
                st.success(f"✅ S-RIM 기준 적정가({srim:,.0f}원) 대비 **{abs(diff):.1f}% 저평가** 상태입니다.")
            else:
                st.warning(f"⚠️ S-RIM 기준 적정가({srim:,.0f}원) 대비 **{diff:.1f}% 고평가** 상태입니다.")
        else:
             st.info("ROE가 너무 낮거나 적자 기업이라 S-RIM 계산이 어렵습니다.")
