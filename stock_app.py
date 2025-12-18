import streamlit as st
import yfinance as yf
import pandas as pd
import time

# -----------------------------------------------------------
# 페이지 설정
# -----------------------------------------------------------
st.set_page_config(page_title="Info Nomad 주식 X-Ray", page_icon="📈", layout="wide")

# -----------------------------------------------------------
# [핵심함수] 안전하게 데이터 가져오기 (Fail-Safe)
# -----------------------------------------------------------
@st.cache_data(ttl=600)  # 10분 캐싱 (너무 길면 실시간성 떨어짐)
def get_safe_stock_data(ticker):
    # 1. 티커 정리
    ticker = ticker.strip().upper()
    stock = yf.Ticker(ticker)
    
    # 결과 담을 변수들 초기화
    data = {
        "name": ticker, "currency": "KRW", "current_price": 0,
        "per": 0, "roe": 0, "peg": 0,
        "graham": 0, "srim": 0,
        "status": "ok" # 상태 체크용
    }

    try:
        # ---------------------------------------------------
        # A. 가격 정보 가져오기 (가장 중요 - 우선 시도)
        # ---------------------------------------------------
        # fast_info는 차단이 거의 안됨
        if hasattr(stock, 'fast_info'):
            data['current_price'] = stock.fast_info.last_price
            data['currency'] = stock.fast_info.currency
        
        # 만약 fast_info가 없으면 history로 시도
        if data['current_price'] == 0:
            hist = stock.history(period='1d')
            if not hist.empty:
                data['current_price'] = hist['Close'].iloc[-1]
            else:
                return None, "존재하지 않는 종목이거나 상장 폐지되었습니다."

        # ---------------------------------------------------
        # B. 재무 정보 가져오기 (여기가 자주 막힘)
        # ---------------------------------------------------
        try:
            info = stock.info # 여기서 에러가 잘 남
            
            data['name'] = info.get('longName', ticker)
            data['per'] = info.get('trailingPE', 0)
            data['roe'] = info.get('returnOnEquity', 0)
            data['peg'] = info.get('pegRatio', 0)
            
            bps = info.get('bookValue', 0)
            eps = info.get('trailingEps', 0)

            # 모델 계산
            if eps > 0 and bps > 0:
                data['graham'] = (22.5 * eps * bps) ** 0.5
            
            if data['roe'] and bps > 0:
                data['srim'] = bps * (data['roe'] / 0.08) # 요구수익률 8%

        except Exception:
            # 재무 데이터만 실패했을 경우 -> 가격만이라도 보여주기 위해 에러 무시
            data['status'] = "partial" # 부분 성공

        return data, None

    except Exception as e:
        return None, f"서버 연결 실패: {str(e)}"

# -----------------------------------------------------------
# [UI] 화면 구성
# -----------------------------------------------------------
st.title("📈 AI 주식 X-Ray 분석기")
st.caption("안정적인 분석을 위해 최적화된 엔진이 가동 중입니다.")

ticker_input = st.text_input("종목 코드 입력 (예: 005930.KS, AAPL):")

if ticker_input:
    with st.spinner('데이터를 정밀 분석 중입니다...'):
        result, error = get_safe_stock_data(ticker_input)

    if error:
        st.error(f"⛔ {error}")
    elif result:
        st.divider()
        
        # 1. 제목 및 현재가 (무조건 표시됨)
        st.subheader(f"{result['name']} ({result['currency']})")
        st.metric("현재 주가", f"{result['current_price']:,.0f}")
        
        # 2. 재무 데이터 상태에 따른 분기 처리
        if result['status'] == "partial":
            st.warning("⚠️ 현재 접속량이 많아 '적정주가 상세 분석'은 일시적으로 제한됩니다. (현재가 정보만 제공)")
        else:
            # 정상적으로 다 가져왔을 때
            c1, c2, c3 = st.columns(3)
            c1.metric("PER", f"{result['per']:.2f}배" if result['per'] else "-")
            c2.metric("ROE", f"{result['roe']*100:.2f}%" if result['roe'] else "-")
            c3.metric("PEG", f"{result['peg']:.2f}" if result['peg'] else "-")
            
            st.write("---")
            st.markdown("#### 📊 적정주가 밴드")
            
            chart_df = pd.DataFrame({
                "모델": ["현재가", "그레이엄", "S-RIM"],
                "가격": [result['current_price'], result['graham'], result['srim']]
            })
            chart_df = chart_df[chart_df['가격'] > 0] # 0인 값 제거
            
            if not chart_df.empty:
                st.bar_chart(chart_df.set_index("모델"))
                
                # 간단 코멘트
                if result['srim'] > 0:
                    diff = (result['current_price'] - result['srim']) / result['srim'] * 100
                    if diff < 0:
                        st.success(f"✅ S-RIM 기준 **{abs(diff):.1f}% 저평가** 상태입니다.")
                    else:
                        st.info(f"⚖️ S-RIM 기준 적정 가치보다 높습니다.")
            else:
                st.info("재무 데이터 부족으로 적정주가 차트를 그릴 수 없습니다.")
