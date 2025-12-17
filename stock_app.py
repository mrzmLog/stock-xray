import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
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
# [함수] 데이터 가져오기 (캐싱 적용: 1시간 동안 저장)
# -----------------------------------------------------------
# @st.cache_data: 한 번 검색한 종목은 3600초(1시간) 동안 야후에 다시 안 물어봄 (차단 방지)
@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_data(ticker_symbol):
    try:
        # 데이터 다운로드 (progress bar 없이 조용히)
        stock = yf.Ticker(ticker_symbol)
        info = stock.info
        
        # 필수 데이터 확인
        if 'currentPrice' not in info:
            # 예외: 가끔 fast_info를 써야 잡히는 경우가 있음
            if hasattr(stock, 'fast_info') and stock.fast_info.last_price:
                current_price = stock.fast_info.last_price
            else:
                return None, "데이터를 찾을 수 없습니다. (상장폐지 또는 티커 오류)"
        else:
            current_price = info['currentPrice']

        # 1. 기본 데이터 추출
        currency = info.get('currency', 'KRW')
        name = info.get('longName', ticker_symbol)
        
        # 2. 가치평가 지표 (없으면 0 처리)
        bps = info.get('bookValue', 0)
        eps = info.get('trailingEps', 0)
        roe = info.get('returnOnEquity', 0) # 0.15 형태로 나옴
        per = info.get('trailingPE', 0)
        peg = info.get('pegRatio', 0)

        # -------------------------------------------------------
        # 모델 계산 로직
        # -------------------------------------------------------
        # 1. 그레이엄
        graham_value = 0
        if eps > 0 and bps > 0:
            graham_value = (22.5 * eps * bps) ** 0.5
        
        # 2. S-RIM (요구수익률 8%)
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
        return None, f"일시적인 서버 오류입니다: {str(e)}"

# -----------------------------------------------------------
# [UI] 웹 화면 구성
# -----------------------------------------------------------
st.title("📈 AI 주식 X-Ray 분석기")
st.markdown("#### :blue[워런 버핏과 사경인의 눈으로] 종목을 진단합니다.")

with st.expander("🔍 사용법 및 티커 입력 가이드", expanded=True):
    st.write("""
    - **한국 주식:** 삼성전자 -> `005930.KS`, 에코프로비엠 -> `247540.KQ`
    - **미국 주식:** 애플 -> `AAPL`, 테슬라 -> `TSLA`
    - *데이터 로딩에 3~5초 정도 걸릴 수 있습니다.*
    """)

ticker = st.text_input("종목 코드(Ticker) 입력:", placeholder="예: 005930.KS")

if ticker:
    # 대문자 변환 및 공백 제거
    ticker = ticker.strip().upper()
    
    with st.spinner(f'{ticker} 분석 데이터를 가져오는 중입니다...'):
        data, error = get_stock_data(ticker)

    if error:
        st.error(f"🚫 {error}")
        st.caption("팁: 잠시 후 다시 시도하거나, 티커가 정확한지 확인해주세요.")
    elif data:
        st.divider()
        st.subheader(f"📊 {data['name']} 진단 결과")
        
        # 1. 핵심 지표
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재 주가", f"{data['current_price']:,.0f} {data['currency']}")
        c2.metric("PER", f"{data['per']:.2f}배" if data['per'] else "-")
        c3.metric("ROE", f"{data['roe']*100:.2f}%" if data['roe'] else "-")
        c4.metric("PEG", f"{data['peg']:.2f}" if data['peg'] else "-")

        st.divider()

        # 2. 차트 데이터
        chart_df = pd.DataFrame({
            "구분": ["현재 주가", "그레이엄 가치", "S-RIM 가치"],
            "가격": [data['current_price'], data['graham_value'], data['srim_value']]
        })
        # 0원인 항목 제거
        chart_df = chart_df[chart_df['가격'] > 0]
        
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("구분"))

        # 3. 상세 리포트
        st.subheader("💡 투자 인사이트")
        
        # S-RIM
        if data['srim_value'] > 0:
            diff = (data['current_price'] - data['srim_value']) / data['srim_value'] * 100
            if diff < 0:
                st.success(f"✅ **S-RIM 저평가:** 적정가보다 **{abs(diff):.1f}%** 저렴합니다.")
            else:
                st.warning(f"⚠️ **S-RIM 고평가:** 적정가보다 **{diff:.1f}%** 높습니다.")
        
        # PEG
        if data['peg'] > 0 and data['peg'] < 1:
            st.caption(f"🚀 **성장주 발견:** PEG가 {data['peg']:.2f}로 저평가 상태입니다.")
            
    else:
        st.warning("데이터를 불러오지 못했습니다.")
