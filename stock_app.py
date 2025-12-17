import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

# -----------------------------------------------------------
# 페이지 기본 설정 (브라우저 탭 이름, 레이아웃 등)
# -----------------------------------------------------------
st.set_page_config(
    page_title="Info Nomad 주식 X-Ray",
    page_icon="📈",
    layout="wide"
)

# -----------------------------------------------------------
# [함수] 데이터 가져오기 및 적정주가 계산
# -----------------------------------------------------------
def get_stock_data(ticker_symbol):
    # 한국 주식(.KS, .KQ)이 아니면 경고 메시지 처리를 위해 확인
    stock = yf.Ticker(ticker_symbol)
    
    try:
        info = stock.info
        
        # 필수 데이터가 없는 경우(상장폐지, 티커 오류 등) 체크
        if 'currentPrice' not in info:
            return None, "데이터를 찾을 수 없습니다. 올바른 티커인지 확인해주세요."

        # 1. 기본 데이터 추출
        current_price = info.get('currentPrice', 0)     # 현재가
        currency = info.get('currency', 'KRW')          # 통화
        name = info.get('longName', ticker_symbol)      # 종목명
        
        # 2. 가치평가를 위한 핵심 지표 (없으면 0 처리하여 에러 방지)
        bps = info.get('bookValue', 0)                  # BPS (주당순자산)
        eps = info.get('trailingEps', 0)                # EPS (주당순이익)
        roe = info.get('returnOnEquity', 0)             # ROE (자기자본이익률) - 소수점(0.15 등)
        per = info.get('trailingPE', 0)                 # PER
        peg = info.get('pegRatio', 0)                   # PEG

        # -------------------------------------------------------
        # [모델 1] 벤저민 그레이엄 모델
        # 공식: sqrt(22.5 * EPS * BPS)
        # -------------------------------------------------------
        graham_value = 0
        if eps > 0 and bps > 0:
            graham_value = (22.5 * eps * bps) ** 0.5
        
        # -------------------------------------------------------
        # [모델 2] S-RIM (사경인 회계사 방식 단순화)
        # 공식: BPS * (ROE / 요구수익률) -> 여기서는 요구수익률을 8%~10% 정도로 가정
        # -------------------------------------------------------
        srim_value = 0
        discount_rate = 0.08  # 요구수익률 8% 가정 (보수적)
        if roe is not None and bps > 0:
            # ROE가 너무 낮으면 적정가가 BPS보다 낮게 나옴
            srim_value = bps * (roe / discount_rate)

        # 결과 딕셔너리 생성
        data = {
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
        }
        return data, None

    except Exception as e:
        return None, f"오류 발생: {str(e)}"

# -----------------------------------------------------------
# [UI] 웹 화면 구성
# -----------------------------------------------------------
st.title("📈 AI 주식 X-Ray 분석기")
st.markdown("#### :blue[워런 버핏과 사경인의 눈으로] 종목을 진단합니다.")

# 사용자 입력창 (사이드바 또는 메인 상단)
with st.expander("🔍 사용법 및 티커 입력 가이드 (여기를 클릭하세요)", expanded=True):
    st.write("""
    - **한국 주식:** 삼성전자 -> `005930.KS` (코스피), 에코프로비엠 -> `247540.KQ` (코스닥)
    - **미국 주식:** 애플 -> `AAPL`, 테슬라 -> `TSLA`
    - **입력 후 Enter**를 치시면 분석이 시작됩니다.
    """)

# 입력창 배치
col_input, col_btn = st.columns([4, 1])
with col_input:
    ticker = st.text_input("종목 코드(Ticker) 입력:", placeholder="예: 005930.KS")

if ticker:
    with st.spinner('야후 파이낸스 서버에서 데이터를 가져오는 중...'):
        data, error = get_stock_data(ticker.strip().upper())

    if error:
        st.error(error)
    elif data:
        # 1. 핵심 요약 카드
        st.divider()
        st.subheader(f"📊 {data['name']} 진단 결과")
        
        # 3단 컬럼으로 주요 지표 표시
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("현재 주가", f"{data['current_price']:,.0f} {data['currency']}")
        m2.metric("PER (주가수익비율)", f"{data['per']:.2f}배" if data['per'] else "N/A")
        m3.metric("ROE (자기자본이익률)", f"{data['roe']*100:.2f}%" if data['roe'] else "N/A")
        m4.metric("PEG (성장성 지표)", f"{data['peg']:.2f}" if data['peg'] else "N/A")

        st.divider()

        # 2. 적정주가 비교 차트 (데이터 전처리)
        chart_data = {
            "구분": ["현재 주가", "그레이엄 적정가", "S-RIM 적정가"],
            "가격": [data['current_price'], data['graham_value'], data['srim_value']]
        }
        df_chart = pd.DataFrame(chart_data)

        # 가격이 0인 경우(계산 불가) 제외
        df_chart = df_chart[df_chart['가격'] > 0]

        # 바 차트 그리기
        st.bar_chart(df_chart.set_index("구분"))

        # 3. 상세 분석 코멘트
        st.subheader("💡 투자 인사이트")
        
        # S-RIM 분석
        if data['srim_value'] > 0:
            diff_srim = (data['current_price'] - data['srim_value']) / data['srim_value'] * 100
            if data['current_price'] < data['srim_value']:
                st.success(f"✅ **S-RIM 기준 저평가:** 적정가 대비 약 **{abs(diff_srim):.1f}% 저렴**합니다. (안전마진 확보)")
            else:
                st.warning(f"⚠️ **S-RIM 기준 고평가:** 적정가 대비 약 **{diff_srim:.1f}% 비쌉니다.** (실적 개선 필요)")
        else:
            st.info("ℹ️ S-RIM 적정가를 계산할 수 없습니다. (ROE 데이터 부족 또는 적자 기업)")

        # 그레이엄 분석
        if data['graham_value'] > 0:
            if data['current_price'] < data['graham_value']:
                st.write(f"- **그레이엄 모델:** 자산가치와 수익력 대비 주가가 저렴합니다. (전통 가치주 관점)")
            else:
                st.write(f"- **그레이엄 모델:** 보수적 관점에서는 주가가 다소 높습니다.")

        # PEG 분석 (성장주 여부)
        if data['peg'] > 0:
            if data['peg'] < 1:
                st.caption(f"🚀 **성장성 점검 (PEG):** {data['peg']:.2f}로 **매우 저평가**된 성장주입니다. (1 미만 추천)")
            elif data['peg'] < 1.5:
                 st.caption(f"⚖️ **성장성 점검 (PEG):** {data['peg']:.2f}로 적정한 성장 프리미엄을 받고 있습니다.")
            else:
                 st.caption(f"🔥 **성장성 점검 (PEG):** {data['peg']:.2f}로 성장에 대한 기대감이 높게 반영되어 있습니다.")

    else:
        st.warning("데이터를 불러오지 못했습니다. 티커를 다시 확인해주세요.")
