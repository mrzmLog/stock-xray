import streamlit as st
import yfinance as yf
import pandas as pd
import requests

# -----------------------------------------------------------
# 페이지 기본 설정
# -----------------------------------------------------------
st.set_page_config(
    page_title="Info Nomad 주식 X-Ray",
    page_icon="📈",
    layout="wide"
)

# -----------------------------------------------------------
# [함수] 데이터 가져오기 (User-Agent 적용 + 캐싱)
# -----------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_data(ticker_symbol):
    try:
        # 1. 가짜 브라우저 세션 만들기 (야후 차단 회피용)
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        })

        # 2. 세션을 포함하여 데이터 요청
        stock = yf.Ticker(ticker_symbol, session=session)
        
        # 데이터가 즉시 안 들어올 때를 대비해 기본 정보 호출 시도
        info = stock.info
        
        # 필수 데이터 확인
        if 'currentPrice' not in info:
             # fast_info로 재시도
            if hasattr(stock, 'fast_info') and stock.fast_info.last_price:
                current_price = stock.fast_info.last_price
            else:
                return None, "데이터를 찾을 수 없습니다. (상장폐지 또는 티커 오류)"
        else:
            current_price = info['currentPrice']

        # 3. 데이터 추출
        currency = info.get('currency', 'KRW')
        name = info.get('longName', ticker_symbol)
        
        bps = info.get('bookValue', 0)
        eps = info.get('trailingEps', 0)
        roe = info.get('returnOnEquity', 0)
        per = info.get('trailingPE', 0)
        peg = info.get('pegRatio', 0)

        # 4. 모델 계산
        # 그레이엄
        graham_value = 0
        if eps > 0 and bps > 0:
            graham_value = (22.5 * eps * bps) ** 0.5
        
        # S-RIM (요구수익률 8%)
        srim_value = 0
        discount_rate = 0.08
        if roe and bps > 0:
             srim_value = bps * (roe / discount_rate)

        return {
            "name": name,
            "currency": currency,
            "current_price": current_price,
            "bps": bps,
            "eps": eps,
            "roe": roe,
            "per": per,
            "peg": peg,
            "graham_value": graham_value,
            "srim_value": srim_value
        }, None

    except Exception as e:
        # 에러 내용을 좀 더 구체적으로 반환
        return None, f"서버 접속 지연: {str(e)}"

# -----------------------------------------------------------
# [UI] 웹 화면 구성
# -----------------------------------------------------------
st.title("📈 AI 주식 X-Ray 분석기")
st.markdown("#### :blue[워런 버핏과 사경인의 눈으로] 종목을 진단합니다.")

with st.expander("🔍 사용법 및 티커 입력 가이드", expanded=True):
    st.write("""
    - **한국 주식:** 삼성전자 -> `005930.KS`, 에코프로비엠 -> `247540.KQ`
    - **미국 주식:** 애플 -> `AAPL`, 테슬라 -> `TSLA`
    - *Tip: 너무 빠르게 연속 조회하면 잠시 제한될 수 있습니다.*
    """)

ticker = st.text_input("종목 코드(Ticker) 입력:", placeholder="예: 005930.KS")

if ticker:
    ticker = ticker.strip().upper()
    
    with st.spinner(f'{ticker} 분석 데이터를 가져오는 중입니다...'):
        data, error = get_stock_data(ticker)

    if error:
        st.warning(f"⚠️ {error}")
        st.info("💡 **해결책:** 10초 정도 기다렸다가 다시 시도하거나, 티커(종목코드)가 정확한지 확인해주세요.")
    elif data:
        st.divider()
        st.subheader(f"📊 {data['name']} 진단 결과")
        
        # 요약 지표
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재 주가", f"{data['current_price']:,.0f} {data['currency']}")
        c2.metric("PER", f"{data['per']:.2f}배" if data['per'] else "-")
        c3.metric("ROE", f"{data['roe']*100:.2f}%" if data['roe'] else "-")
        c4.metric("PEG", f"{data['peg']:.2f}" if data['peg'] else "-")

        st.divider()

        # 차트
        chart_df = pd.DataFrame({
            "구분": ["현재 주가", "그레이엄 가치", "S-RIM 가치"],
            "가격": [data['current_price'], data['graham_value'], data['srim_value']]
        })
        chart_df = chart_df[chart_df['가격'] > 0]
        
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("구분"))

        # 리포트
        st.subheader("💡 투자 인사이트")
        
        # S-RIM
        if data['srim_value'] > 0:
            diff = (data['current_price'] - data['srim_value']) / data['srim_value'] * 100
            if diff < 0:
                st.success(f"✅ **S-RIM 저평가:** 적정가보다 **{abs(diff):.1f}%** 저렴합니다.")
            else:
                st.warning(f"⚠️ **S-RIM 고평가:** 적정가보다 **{diff:.1f}%** 높습니다.")
        else:
            st.info("ℹ️ ROE 데이터가 부족하여 S-RIM 계산이 어렵습니다.")

        # 그레이엄
        if data['graham_value'] > 0:
             if data['current_price'] < data['graham_value']:
                 st.write("- **그레이엄 모델:** 자산/수익 가치 대비 저렴합니다.")
        
        # PEG
        if data['peg'] > 0 and data['peg'] < 1:
            st.caption(f"🚀 **성장주 발견:** PEG {data['peg']:.2f} (1 미만)로 저평가 성장주입니다.")
