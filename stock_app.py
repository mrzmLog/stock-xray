import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import numpy as np
import re
import altair as alt

# -----------------------------------------------------------
# [1] 페이지 및 스타일 설정
# -----------------------------------------------------------
st.set_page_config(page_title="적정주가 산출 계산기", page_icon="🧮", layout="wide")

st.markdown("""
<style>
    /* 기본 폰트 설정 */
    html, body, [class*="css"] {
        font-family: 'Pretendard', sans-serif;
        font-size: 1.05rem;
    }
    
    /* 제목 스타일 */
    h1 { font-size: 2.0rem !important; font-weight: 800 !important; color: #111; }
    
    /* 리포트 헤더 (배경색 추가) */
    .report-header {
        background-color: #f1f3f5;
        padding: 12px 20px;
        border-radius: 8px;
        font-size: 1.2rem;
        font-weight: 700;
        color: #343a40;
        margin-bottom: 15px;
        border-left: 5px solid #4c6ef5;
    }

    /* 메트릭 카드 */
    .metric-card {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
    .metric-label { font-size: 0.9rem; color: #666; margin-bottom: 5px; }
    
    /* 결과 박스 */
    .result-box-success {
        background-color: #e6f9ed;
        border: 1px solid #b7ebc5;
        color: #1f7a38;
        padding: 15px;
        border-radius: 10px;
        font-weight: bold;
    }
    .result-box-warning {
        background-color: #fff8e6;
        border: 1px solid #ffeeba;
        color: #997404;
        padding: 15px;
        border-radius: 10px;
        font-weight: bold;
    }
    
    /* 팁 박스 */
    .tip-box {
        background-color: #f8f9fa;
        border-left: 4px solid #007bff;
        padding: 10px;
        margin-top: 10px;
        font-size: 0.9rem;
        color: #555;
    }

    /* 최종 결과 테이블 스타일 */
    .final-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 1.1rem;
        margin-bottom: 20px;
    }
    .final-table th {
        background-color: #4c6ef5;
        color: white;
        padding: 12px;
        text-align: center;
        border: 1px solid #ddd;
    }
    .final-table td {
        padding: 10px;
        text-align: center;
        border: 1px solid #ddd;
        font-weight: 600;
    }
    .final-table tr:nth-child(even) {background-color: #f2f2f2;}

    /* 면책 조항 박스 */
    .disclaimer-box {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        padding: 20px;
        border-radius: 10px;
        font-size: 1.0rem;
        color: #856404;
        line-height: 1.6;
        margin-top: 30px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🧮 적정주가 산출 계산기")
st.caption("Last Updated : 2025. 12 | Powered by info Nomad")

# -----------------------------------------------------------
# [1] 모델 설명
# -----------------------------------------------------------
with st.expander("📘 분석 모델 및 데이터 기준 설명 (열기)", expanded=False):
    st.markdown("""
    - **데이터 기준:** 네이버 금융의 **'최근 연간 실적'**만 사용합니다. (분기 데이터 자동 제외)
    - **예상치(E) 활용:** 증권사 컨센서스(예상치)가 있는 경우 미래 가치를 우선 반영합니다.
    - **S-RIM:** 자산가치(BPS) + 초과이익가치(ROE). (이익이 꾸준한 우량주용)
    - **벤저민 그레이엄:** BPS와 EPS의 기하평균. (자산가치 중시)
    - **피터 린치 (PEG):** 연간 EPS 성장률(CAGR) 기반. (성장주용)
    """)

# -----------------------------------------------------------
# [2] 데이터 크롤링 함수
# -----------------------------------------------------------
@st.cache_data
def get_stock_list():
    df_krx = fdr.StockListing('KRX')
    df_krx['Search_Name'] = df_krx['Name'] + " (" + df_krx['Code'] + ")"
    return df_krx[['Search_Name', 'Code', 'Name']]

@st.cache_data(ttl=600) 
def get_stock_analysis(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        dfs = pd.read_html(response.text)
        
        financials = None
        for df in dfs:
            if '매출액' in str(df.iloc[:,0]) or '최근 연간 실적' in str(df.columns):
                financials = df
                break
        
        if financials is None:
            return None, "재무 데이터를 찾을 수 없습니다."

        # 컬럼 정리
        if isinstance(financials.columns, pd.MultiIndex):
            new_columns = []
            drop_indices = []
            for i, col_tuple in enumerate(financials.columns):
                if any("분기" in str(x) for x in col_tuple):
                    drop_indices.append(i)
                    continue
                date_part = None
                for part in col_tuple:
                    if re.search(r'20\d{2}\.\d{2}', str(part)) or "(E)" in str(part):
                        date_part = part
                        break
                new_columns.append(date_part if date_part else "Descriptor")
            
            financials = financials.drop(financials.columns[drop_indices], axis=1)
            financials.columns = new_columns
        else:
            cols_to_drop = [c for c in financials.columns if "분기" in str(c)]
            financials = financials.drop(columns=cols_to_drop)

        if "Descriptor" in financials.columns:
            financials = financials.set_index("Descriptor")
        else:
            financials = financials.set_index(financials.columns[0])

        valid_cols = [c for c in financials.columns if re.search(r'20\d{2}\.\d{2}', str(c))]
        if not valid_cols:
            return None, f"연간 실적 식별 실패"
            
        financials = financials[valid_cols]
        target_col = valid_cols[-1] 
        is_estimate = "(E)" in target_col or "E" in target_col

        # 히스토리 데이터
        key_indices = ['매출액', '영업이익', '당기순이익', '영업이익률', '부채비율', 'ROE', 'EPS', 'BPS', 'PER', 'PBR']
        history_df = financials.loc[financials.index.str.contains('|'.join(key_indices), na=False)]
        
        # 값 추출 헬퍼
        def get_val(row_key, col_name):
            try:
                row = financials.loc[financials.index.str.contains(row_key, na=False)]
                if row.empty: return 0
                val = row[col_name].iloc[0]
                if pd.isna(val) or str(val).strip() in ['-', '', 'nan']:
                    prev_idx = valid_cols.index(col_name) - 1
                    if prev_idx >= 0:
                        val = row[valid_cols[prev_idx]].iloc[0]
                return float(str(val).replace(',', ''))
            except:
                return 0

        roe = get_val('ROE', target_col)
        eps = get_val('EPS', target_col)
        bps = get_val('BPS', target_col)
        per = get_val('PER', target_col)
        
        # CAGR
        eps_growth_rate = 0
        try:
            start_col = valid_cols[0]
            start_year = int(re.search(r'20\d{2}', str(start_col)).group())
            end_year = int(re.search(r'20\d{2}', str(target_col)).group())
            years = end_year - start_year
            if years > 0:
                eps_start = get_val('EPS', start_col)
                eps_end = get_val('EPS', target_col)
                if eps_start > 0 and eps_end > 0:
                    eps_growth_rate = ((eps_end / eps_start) ** (1/years) - 1) * 100
        except:
            eps_growth_rate = 0

        # 주가 정보
        df_price = fdr.DataReader(code)
        if df_price.empty: return None, "주가 정보 오류"
        
        current_price = df_price['Close'].iloc[-1]
        prev_price = df_price['Close'].iloc[-2]
        price_diff = current_price - prev_price
        price_pct = (price_diff / prev_price) * 100
        
        return {
            "code": code,
            "price": current_price,
            "price_diff": price_diff,
            "price_pct": price_pct,
            "roe": roe,
            "eps": eps,
            "bps": bps,
            "per": per,
            "eps_growth": eps_growth_rate,
            "target_year": target_col,
            "is_estimate": is_estimate,
            "history_df": history_df
        }, None

    except Exception as e:
        return None, f"오류 발생: {str(e)}"

# -----------------------------------------------------------
# [3] 표 포맷팅
# -----------------------------------------------------------
def format_financial_table(df):
    formatted_df = df.copy()
    for col in formatted_df.columns:
        for idx in formatted_df.index:
            try:
                val = formatted_df.loc[idx, col]
                if pd.isna(val) or str(val).strip() in ['-', '', 'nan']:
                    formatted_df.loc[idx, col] = "-"
                    continue
                
                val_float = float(str(val).replace(',', ''))
                idx_clean = idx.replace(' ', '') 
                
                if '율' in idx_clean or 'ROE' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:.2f} %"
                elif '매출액' in idx_clean or '영업이익' in idx_clean or '당기순이익' in idx_clean:
                     formatted_df.loc[idx, col] = f"{val_float:,.0f} 억"
                elif 'EPS' in idx_clean or 'BPS' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:,.0f} 원"
                elif 'PER' in idx_clean or 'PBR' in idx_clean:
                    formatted_df.loc[idx, col] = f"{val_float:.2f} 배"
                else:
                    formatted_df.loc[idx, col] = f"{val_float:,.2f}"
            except:
                continue
    return formatted_df

# -----------------------------------------------------------
# [4] 분석 인사이트
# -----------------------------------------------------------
def get_analysis_comment(model_name, fair_value, current_price, required_return=None):
    if fair_value <= 0:
        return "데이터 부족 또는 적자로 인해 계산할 수 없습니다."
    
    diff = (current_price - fair_value) / fair_value * 100
    
    if abs(diff) < 10:
        return "현재 주가는 적정가치와 비슷한 수준(<b>적정</b>)입니다."
    
    if diff > 0: 
        if model_name == "S-RIM":
            return "현재 주가에 <b>미래 성장 기대감(프리미엄)</b>이 반영되어 있습니다."
        else:
            return "펀더멘털 대비 주가가 <b>높게 형성</b>되어 있습니다."
    else: 
        if diff < -30:
            return "기업 가치 대비 <b>현저한 저평가</b> 구간입니다. (안전마진 확보)"
        return "적정 가치보다 <b>저렴한</b> 상태입니다."

# -----------------------------------------------------------
# [5] UI: 상단 검색 및 설정 (들여쓰기 수정 완료)
# -----------------------------------------------------------
with st.expander("🔍 종목 선택 및 설정 (여기를 클릭하여 종목을 검색하세요)", expanded=True):
    col_input1, col_input2 = st.columns([1, 1])
    
    with col_input1:
        try:
            with st.spinner("종목 리스트 로딩..."):
                stock_list = get_stock_list()
            selected_stock = st.selectbox(
                "종목 검색", stock_list['Search_Name'], index=None, placeholder="종목명 입력 (예: 삼성전자)"
            )
        except:
            st.error("종목 로딩 실패")
            selected_stock = None
            
    with col_input2:
        srim_option = st.radio(
            "S-RIM 요구수익률(k) 기준:", 
            ("BBB- 회사채 (8.0%)", "한국주식 평균 (10.0%)", "국채 금리 (4.0%)", "직접 입력"), 
            index=0, horizontal=True
        )
        # [수정] 들여쓰기 라인 정렬 완료
        if "8.0%" in srim_option: default_k = 8.0
        elif "10.0%" in srim_option: default_k = 10.0
        elif "4.0%" in srim_option: default_k = 4.0
        else: default_k = 8.0
        
        required_return = st.slider("요구수익률 상세 조정 (%)", 2.0, 20.0, default_k, 0.1)

# -----------------------------------------------------------
# 메인 로직 및 리포트 출력
# -----------------------------------------------------------
if selected_stock:
    code = selected_stock.split('(')[-1].replace(')', '')
    stock_name = selected_stock.split('(')[0]

    with st.spinner(f"'{stock_name}' 데이터 분석 중..."):
        data, error = get_stock_analysis(code)

    if error:
        st.error(error)
    elif data:
        # 계산
        srim = 0
        if data['bps'] > 0:
            excess_return_value = data['bps'] * (data['roe'] - required_return) / 100 
            srim = data['bps'] + (excess_return_value / (required_return / 100))

        graham = 0
        if data['eps'] > 0 and data['bps'] > 0:
            graham = (22.5 * data['eps'] * data['bps']) ** 0.5
            
        peter_lynch = 0
        growth_cap = min(data['eps_growth'], 30)
        if data['eps'] > 0 and growth_cap > 0:
            peter_lynch = data['eps'] * growth_cap

        # [헤더] 주가 표시
        st.divider()
        st.subheader(f"🏢 {stock_name} ({data['code']})")
        
        # 주가 등락 색상 결정
        price_color = "red" if data['price_diff'] > 0 else "blue" if data['price_diff'] < 0 else "black"
        arrow = "▲" if data['price_diff'] > 0 else "▼" if data['price_diff'] < 0 else "-"
        
        st.markdown(f"""
        <h2 style='margin:0;'>{data['price']:,.0f}원 
        <span style='font-size:0.6em; color:{price_color};'>
        {arrow} {abs(data['price_diff']):,.0f} ({data['price_pct']:.2f}%)
        </span></h2>
        """, unsafe_allow_html=True)
        
        st.divider()

        # [섹션 1] 실적 표
        st.markdown("##### 1️⃣ 최근 연간 실적 흐름")
        st.caption("※ 모바일에서는 표를 좌우로 밀어서 확인하세요.")
        display_df = format_financial_table(data['history_df'])
        st.dataframe(display_df, use_container_width=True)
        if data['is_estimate']:
            st.markdown(f"<div style='font-size:0.9rem; color:#555;'>💡 참고: '<b>{data['target_year']}</b>' 데이터는 증권사 <b>예상치(Consensus)</b>입니다.</div>", unsafe_allow_html=True)

        st.divider()

        # [섹션 2] 적정주가 리포트
        st.markdown(f"##### 2️⃣ 적정주가 산출 리포트 (기준: {data['target_year']})")
        
        def draw_report_card(title, inputs, result_value, formula, comment):
            st.markdown(f"<div class='report-header'>{title}</div>", unsafe_allow_html=True)
            c1, c2 = st.columns([1, 1.2])
            
            with c1:
                input_html = "".join([f"<div>• {k}: <b>{v}</b></div>" for k, v in inputs.items()])
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">입력 데이터</div>
                    {input_html}
                </div>
                """, unsafe_allow_html=True)
            
            with c2:
                res_cls = "result-box-success" if "저평가" in comment or "저렴" in comment else "result-box-warning"
                if result_value <= 0: res_cls = "result-box-warning"
                val_str = f"{result_value:,.0f}원" if result_value > 0 else "계산 불가"
                
                st.markdown(f"""
                <div class="{res_cls}">
                    <div style="font-size:0.9rem; color:#555;">적정주가</div>
                    <div style="font-size:1.4rem;">{val_str}</div>
                </div>
                <div class="tip-box">
                    <b>🤖 분석 의견:</b><br>{comment}
                </div>
                """, unsafe_allow_html=True)
            
            with st.expander("수식 보기"):
                st.latex(formula)
            st.write("") 

        # S-RIM
        srim_inputs = {
            "BPS (BPS)": f"{data['bps']:,.0f}원",
            "ROE (ROE)": f"{data['roe']}%",
            "요구수익률 (k)": f"{required_return}%"
        }
        srim_comment = get_analysis_comment("S-RIM", srim, data['price'], required_return)
        draw_report_card("① S-RIM (사경인 모델)", srim_inputs, srim, 
                         r"BPS + \frac{BPS \times (ROE - k)}{k}", srim_comment)

        # 그레이엄
        graham_inputs = {
            "EPS (EPS)": f"{data['eps']:,.0f}원",
            "BPS (BPS)": f"{data['bps']:,.0f}원",
            "상수": "22.5"
        }
        graham_comment = get_analysis_comment("그레이엄", graham, data['price'])
        draw_report_card("② 벤저민 그레이엄 (NCAV)", graham_inputs, graham, 
                         r"\sqrt{22.5 \times EPS \times BPS}", graham_comment)

        # 피터 린치
        lynch_inputs = {
            "EPS (EPS)": f"{data['eps']:,.0f}원",
            "성장률 (G)": f"{data['eps_growth']:.1f}%",
            "비고": "Max 30% 제한"
        }
        lynch_comment = get_analysis_comment("PEG", peter_lynch, data['price'])
        draw_report_card("③ 피터 린치 (PEG)", lynch_inputs, peter_lynch, 
                         r"EPS \times Growth Rate", lynch_comment)

        st.divider()

        # [섹션 3] 최종 요약
        st.markdown("##### 3️⃣ 최종 결론")
        
        summary = pd.DataFrame({
            "모델": ["현재 주가", "S-RIM", "그레이엄", "피터 린치"],
            "가격": [data['price'], srim if srim > 0 else 0, graham if graham > 0 else 0, peter_lynch if peter_lynch > 0 else 0]
        })
        
        summary_disp = summary.copy()
        summary_disp['가격'] = summary_disp['가격'].apply(lambda x: f"{x:,.0f}원" if x > 0 else "-")
        
        c_final1, c_final2 = st.columns([1, 1])
        
        with c_final1:
            table_html = "<table class='final-table'><thead><tr><th>모델</th><th>적정 주가</th></tr></thead><tbody>"
            for index, row in summary_disp.iterrows():
                table_html += f"<tr><td>{row['모델']}</td><td>{row['가격']}</td></tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)
            
        with c_final2:
            chart_data = summary[summary['가격'] > 0]
            chart = alt.Chart(chart_data).mark_bar().encode(
                x=alt.X('모델', sort=None),
                y='가격',
                color=alt.Color('모델', legend=None, scale=alt.Scale(scheme='category10')), 
                tooltip=['모델', '가격']
            ).properties(
                height=300
            )
            st.altair_chart(chart, use_container_width=True)

    # 면책 조항
    st.markdown("""
    <div class="disclaimer-box">
        <b>[면책 조항]</b><br>
        본 적정주가 계산기는 S-RIM, 벤저민 그레이엄 등 널리 알려진 투자 대가들의 가치평가 모델을 기반으로 참고용 데이터를 제공합니다. 
        제공되는 모든 정보는 단순 계산 결과이며, 기업의 질적 가치나 돌발 변수를 반영하지 않습니다. 
        <b>투자에 대한 모든 판단과 책임은 투자자 본인에게 있습니다.</b>
    </div>
    """, unsafe_allow_html=True)

else:
    st.info("👆 상단의 **'종목 선택 및 설정'**을 눌러 분석할 종목을 검색해주세요.")
