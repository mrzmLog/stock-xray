import streamlit as st
import yfinance as yf
import pandas as pd
import time

# -----------------------------------------------------------
# 페이지 기본 설정
# -----------------------------------------------------------
st.set_page_config(
    page_title="Info Nomad 주식 X-Ray",
    page_icon="📈",
    layout="wide"
)

# -----------------------------------------------------------
# [함수] 데이터 가져오기 (실패 시 None 반환)
# -----------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_stock_data_auto(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # 1. 가격 정보 (필수)
        # fast_info가 차단 확률이 낮음
        if hasattr(stock, 'fast_info'):
            current_price = stock.fast_info.last_price
            currency = stock.fast_info.currency
        else:
            # history로 재시도
            hist = stock.history(period='1d')
            if hist.empty: return None
            current_price = hist['Close'].iloc[-1]
            currency = "KRW" # 추정

        # 2. 재무 정보 (여기서 에러가 자주 남 -> 실패하면 수동 모드로 유도)
        info = stock.info
        
        name = info.get('longName', ticker_symbol)
        bps = info.get('bookValue', 0)
        eps = info.get('trailingEps', 0)
        roe = info.get('returnOnEquity', 0)
        per = info.get('trailingPE', 0)
        peg = info.get('pegRatio', 0)

        return {
            "success": True,
            "name": name,
            "currency": currency,
            "current_price": current_price,
            "bps": bps,
            "eps": eps,
            "roe": roe,
            "per": per,
            "peg": peg
        }

    except Exception:
        return None # 실패 신호

# -----------------------------------------------------------
# [함수] 적정주가 계산 로직 (공통 사용)
# -----------------------------------------------------------
def calculate_value(current_price, eps, bps, roe):
    # 그레이엄
    graham = 0
    if eps > 0 and bps > 0:
        graham = (22.5 * eps * bps) ** 0.5
    
    # S-RIM (요구수익률 8%)
    srim = 0
    if roe and bps > 0:
        srim = bps * (roe / 0.08)
        
    return graham, srim

# -----------------------------------------------------------
# [UI] 화면 구성
# -----------------------------------------------------------
st.title("📈 AI 주식 X-Ray 분석기")
st.markdown("#### :blue[워런 버핏과 사경인의 눈으로] 종목을 진단합니다.")

with st.expander("🔍 사용법 및 티커 입력 가이드", expanded=True):
    st.write("""
    - **한국 주식:** `005930.KS`(삼성전자), `247540.KQ`(에코프로비엠)
    - **미국 주식:** `AAPL`(애플), `TSLA`(테슬라)
    - **알림:** 데이터 자동 수집이 지연될 경우, **수동 입력창**이 자동으로 열립니다.
    """)

ticker = st.text_input("종목 코드(Ticker) 입력:", placeholder="예: 005930.KS")

# 변수 초기화
data = None
manual_mode = False

if ticker:
    ticker = ticker.strip().upper()
    
    # 1. 자동 수집 시도
    with st.spinner('데이터 분석 중...'):
        data = get_stock_data_auto(ticker)
    
    # 2. 실패 시 수동 모드 활성화
    if data is None:
        st.warning("⚠️ 접속량이 많아 데이터를 자동으로 불러오지 못했습니다. **아래에 수치를 직접 입력해주세요.**")
        manual_mode = True
        
        # 수동 입력 폼
        st.divider()
        st.subheader("📝 데이터 수동 입력")
        c1, c2, c3, c4 = st.columns(4)
        in_price = c1.number_input("현재 주가", value=0)
        in_eps = c2.number_input("EPS (주당순이익)", value=0)
        in_bps = c3.number_input("BPS (주당순자산)", value=0)
        in_roe = c4.number_input("ROE (예: 0.15)", value=0.0, format="%.2f")
        
        if st.button("분석 결과 보기"):
            data = {
                "success": True,
                "name": ticker,
                "currency": "User Input",
                "current_price": in_price,
                "eps": in_eps,
                "bps": in_bps,
                "roe": in_roe,
                "per": 0, "peg": 0 # 수동 입력에선 생략
            }
    
    # 3. 결과 리포트 출력 (자동 or 수동 성공 시)
    if data and data['success']:
        # 계산 실행
        graham, srim = calculate_value(data['current_price'], data['eps'], data['bps'], data['roe'])
        
        st.divider()
        st.subheader(f"📊 {data['name']} 분석 결과")
        
        # 차트 데이터
        chart_df = pd.DataFrame({
            "구분": ["현재 주가", "그레이엄 가치", "S-RIM 가치"],
            "가격": [data['current_price'], graham, srim]
        })
        chart_df = chart_df[chart_df['가격'] > 0]
        
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("구분"))
            
        # 상세 코멘트
        st.subheader("💡 투자 인사이트")
        
        # S-RIM
        if srim > 0:
            diff = (data['current_price'] - srim) / srim * 100
            if diff < 0:
                st.success(f"✅ **S-RIM 저평가:** 적정가({srim:,.0f})보다 **{abs(diff):.1f}%** 쌉니다.")
            else:
                st.warning(f"⚠️ **S-RIM 고평가:** 적정가({srim:,.0f})보다 **{diff:.1f}%** 비쌉니다.")
        elif manual_mode:
            st.info("ROE와 BPS를 입력하면 S-RIM 적정가를 계산해드립니다.")
            
        # 그레이엄
        if graham > 0:
             if data['current_price'] < graham:
                 st.write(f"- **그레이엄 모델:** 가치({graham:,.0f}) 대비 저평가 상태입니다.")
             else:
                 st.write(f"- **그레이엄 모델:** 가치({graham:,.0f}) 대비 고평가 상태입니다.")
