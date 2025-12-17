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
# [핵심] 재시도(Retry) 기능이 포함된 데이터 가져오기 함수
# -----------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_data_with_retry(ticker_symbol):
    max_retries = 3  # 최대 3번까지 재시도
    
    for attempt in range(max_retries):
        try:
            # yfinance 호출 (별도 세션 설정 없이 순정 사용)
            stock = yf.Ticker(ticker_symbol)
            info = stock.info
            
            # 필수 데이터(현재가) 확인
            # 1차 시도: 일반 info에서 찾기
            current_price = info.get('currentPrice')
            
            # 2차 시도: fast_info에서 찾기 (데이터 누락 대비)
            if current_price is None:
                if hasattr(stock, 'fast_info') and stock.fast_info.last_price:
                    current_price = stock.fast_info.last_price
            
            # 그래도 없으면 에러 처리 (다음 시도로 넘어감)
            if current_price is None:
                raise ValueError("가격 데이터를 찾을 수 없습니다.")

            # 여기까지 오면 성공! 데이터 추출 시작
            currency = info.get('currency', 'KRW')
            name = info.get('longName', ticker_symbol)
            
            bps = info.get('bookValue', 0)
            eps = info.get('trailingEps', 0)
            roe = info.get('returnOnEquity', 0)
            per = info.get('trailingPE', 0)
            peg = info.get('pegRatio', 0)

            # 모델 계산
            # 1. 그레이엄
            graham_value = 0
            if eps is not None and bps is not None and eps > 0 and bps > 0:
                graham_value = (22.5 * eps * bps) ** 0.5
            
            # 2. S-RIM (요구수익률 8%)
            srim_value = 0
            discount_rate = 0.08
            if roe is not None and bps is not None and bps > 0:
                 srim_value = bps * (roe / discount_rate)

            # 성공 데이터 반환
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
            # 실패 시 잠시 대기 후 재시도
            time.sleep(1) 
            continue # 다음 반복(attempt)으로 넘어감
            
    # 3번 다 실패했을 경우
    return None, "접속량이 많아 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."

# -----------------------------------------------------------
# [UI] 웹 화면 구성
# -----------------------------------------------------------
st.title("📈 AI 주식 X-Ray 분석기")
st.markdown("#### :blue[워런 버핏과 사경인의 눈으로] 종목을 진단합니다.")

with st.expander("🔍 사용법 및 티커 입력 가이드", expanded=True):
    st.write("""
    - **한국 주식:** 삼성전자 -> `005930.KS`, 에코프로비엠 -> `247540.KQ`
    - **미국 주식:** 애플 -> `AAPL`, 테슬라 -> `TSLA`
    """)

ticker = st.text_input("종목 코드(Ticker) 입력:", placeholder="예: 005930.KS")

if ticker:
    ticker = ticker.strip().upper()
    
    # 로딩 메시지를 부드럽게 변경
    with st.spinner(f'{ticker} 분석 중입니다... (최대 5초 소요)'):
        data, error = get_stock_data_with_retry(ticker)

    if error:
        st.warning(f"⚠️ {error}")
    elif data:
        st.divider()
        st.subheader(f"📊 {data['name']} 진단 결과")
        
        # 1. 요약 지표 (None 값 처리 강화)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재 주가", f"{data['current_price']:,.0f} {data['currency']}")
        
        per_str = f"{data['per']:.2f}배" if data['per'] else "-"
        c2.metric("PER", per_str)
        
        roe_str = f"{data['roe']*100:.2f}%" if data['roe'] else "-"
        c3.metric("ROE", roe_str)
        
        peg_str = f"{data['peg']:.2f}" if data['peg'] else "-"
        c4.metric("PEG", peg_str)

        st.divider()

        # 2. 차트
        chart_df = pd.DataFrame({
            "구분": ["현재 주가", "그레이엄 가치", "S-RIM 가치"],
            "가격": [data['current_price'], data['graham_value'], data['srim_value']]
        })
        chart_df = chart_df[chart_df['가격'] > 0]
        
        if not chart_df.empty:
            st.bar_chart(chart_df.set_index("구분"))
        else:
            st.info("적정주가를 계산하기 위한 재무 데이터가 부족합니다.")

        # 3. 리포트
        st.subheader("💡 투자 인사이트")
        
        # S-RIM
        if data['srim_value'] > 0:
            diff = (data['current_price'] - data['srim_value']) / data['srim_value'] * 100
            if diff < 0:
                st.success(f"✅ **S-RIM 저평가:** 적정가({data['srim_value']:,.0f})보다 **{abs(diff):.1f}%** 저렴합니다.")
            else:
                st.warning(f"⚠️ **S-RIM 고평가:** 적정가({data['srim_value']:,.0f})보다 **{diff:.1f}%** 높습니다.")
        
        # 그레이엄
        if data['graham_value'] > 0:
             if data['current_price'] < data['graham_value']:
                 st.write(f"- **그레이엄 모델:** 자산/수익 가치({data['graham_value']:,.0f}) 대비 저렴합니다.")
             else:
                 st.write(f"- **그레이엄 모델:** 보수적 관점의 가치({data['graham_value']:,.0f})보다는 높습니다.")
