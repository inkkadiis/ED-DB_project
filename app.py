import streamlit as st
import pandas as pd
import re
import os
import io
from dotenv import load_dotenv
import streamlit.components.v1 as components
import urllib.parse

# .env 파일 로드
load_dotenv()
KAKAO_JS_KEY = os.getenv("KAKAO_JS_KEY")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

# ==========================================
# [설정] 필터링 및 정제 규칙
# ==========================================
MIN_EMPLOYEES = 15       # 최소 인원
MAX_EMPLOYEES = 300      # 최대 인원
INDUSTRY_MIN = 10        # 산업코드 시작
INDUSTRY_MAX = 34        # 산업코드 끝
APPEND_NAME = True       # 주소 뒤에 공장명 붙일지 여부
# ==========================================

st.set_page_config(layout="wide", page_title="전국 공장 DB 검수기")

# --- [로그인 기능] ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    pwd = st.text_input("접속 비밀번호를 입력하세요", type="password")
    if pwd == ACCESS_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    else:
        st.stop()

# --- [데이터 처리 엔진] ---
@st.cache_data
def load_and_filter(file):
    # 파일 확장자 확인 (엑셀 vs CSV)
    if file.name.endswith('.xlsx'):
        df = pd.read_excel(file, header=1)
    else:
        df = pd.read_csv(file, header=1)
    
    # 1. 종업원수 및 기업구분 필터링
    df['종업원수'] = pd.to_numeric(df['종업원수'], errors='coerce')
    df = df[(df['종업원수'] >= MIN_EMPLOYEES) & (df['종업원수'] <= MAX_EMPLOYEES)]
    df = df[df['기업구분'].str.contains('소기업|중기업', na=False)]
    
    # 2. 산업코드 필터링
    def check_ind(code):
        if pd.isna(code): return False
        c = str(code).split(',')[0].strip()[:2]
        return c.isdigit() and INDUSTRY_MIN <= int(c) <= INDUSTRY_MAX
    
    df = df[df['업종코드'].apply(check_ind)]
    
    # 3. 주소 정제 함수
    def clean_addr(row):
        addr = str(row['주소'])
        name = str(row['공장명'])
        clean_a = addr
        while re.search(r'\([^()]*\)', clean_a):
            clean_a = re.sub(r'\([^()]*\)', '', clean_a)
        clean_a = clean_a.replace('(', '').replace(')', '')
        clean_a = re.sub(r'외\s?\d?필지.*', '', clean_a)
        clean_a = re.sub(r'외\s?\d?.*', '', clean_a)
        clean_a = re.sub(r'\s+', ' ', clean_a).strip().rstrip(',')
        final_a = f"{clean_a} {name}" if APPEND_NAME else clean_a
        return pd.Series([clean_a, final_a])

    df[['검색용주소', '최종주소']] = df.apply(clean_addr, axis=1)
    df = df.drop_duplicates(subset=['검색용주소'])
    df['검수결과'] = "미검수"
    return df.reset_index(drop=True)

# --- [UI 레이아웃] ---
st.title("🏭 전국 공장 DB 검수 시스템")

uploaded_file = st.file_uploader("공장 DB 파일을 업로드하세요 (CSV 또는 XLSX)", type=['csv', 'xlsx'])

if uploaded_file:
    if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
        st.session_state.df = load_and_filter(uploaded_file)
        st.session_state.current_file = uploaded_file.name
    
    df = st.session_state.df
    
    # 상단 대시보드
    col1, col2, col3 = st.columns(3)
    total = len(df)
    done = len(df[df['검수결과'] != "미검수"])
    pass_cnt = len(df[df['검수결과'] == "PASS"])
    
    col1.metric("전체 타겟", f"{total}건")
    col2.metric("검수 진행", f"{done}건 ({int(done/total*100) if total > 0 else 0}%)")
    col3.metric("최종 PASS", f"{pass_cnt}건")

    st.divider()

    # 메인 작업창
    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.subheader("검수 리스트")
        pending_df = df[df['검수결과'] == "미검수"]
        if not pending_df.empty:
            target_idx = pending_df.index[0]
            target_row = df.iloc[target_idx]
            
            st.info(f"현재 검수 중: **{target_row['공장명']}**")
            st.write(f"📍 {target_row['최종주소']}")
            
            c1, c2 = st.columns(2)
            if c1.button("✅ PASS (가동중)", use_container_width=True):
                st.session_state.df.at[target_idx, '검수결과'] = "PASS"
                st.rerun()
            if c2.button("❌ 폐업/철거/이전", use_container_width=True):
                st.session_state.df.at[target_idx, '검수결과'] = "폐업"
                st.rerun()
        else:
            st.success("🎉 모든 검수가 완료되었습니다!")

    with right_col:
        if not pending_df.empty:
            search_addr = target_row['검색용주소']
            encoded_addr = urllib.parse.quote(search_addr)
            # GitHub Pages 기반 지도 경로
            map_url = f"https://inkkadiis.github.io/ED-DB_project/static/map.html?addr={encoded_addr}&key={KAKAO_JS_KEY}"
            components.iframe(map_url, height=550, scrolling=False)

   # --- [다운로드 섹션] ---
    st.divider()
    st.subheader("📦 결과 다운로드")
    
    # 기존 업로드된 파일명에서 확장자(.xlsx, .csv) 제거 후 순수 이름만 추출
    original_filename = os.path.splitext(st.session_state.current_file)[0]
    
    # 버튼과 설명을 담을 3개의 구역(컬럼) 생성
    d_col1, d_col2, d_col3 = st.columns(3)
    
    # ---------------------------------------------------------
    # 1. 데이터 클리닝이 된 파일
    # ---------------------------------------------------------
    with d_col1:
        st.markdown("#### 📄 1. 데이터 클리닝 원본")
        st.caption("조건(종업원수, 산업코드)에 맞게 필터링되고, 주소 정제(괄호 제거 등)가 완료된 **검수 전 전체 원본 데이터**입니다.")
        
        # 다운로드 전 '검수결과' 컬럼 삭제 (에러 방지를 위해 errors='ignore' 추가)
        df_download_1 = df.drop(columns=['검수결과'], errors='ignore')
        
        output1 = io.BytesIO()
        with pd.ExcelWriter(output1, engine='openpyxl') as writer:
            df_download_1.to_excel(writer, index=False, sheet_name='클리닝완료_전체')
        excel_data1 = output1.getvalue()
        
        st.download_button(
            label="다운로드",
            data=excel_data1,
            file_name=f"{original_filename}_1_cleaned_data_master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # ---------------------------------------------------------
    # 2. PASS 된 애들만 모여 있는 파일
    # ---------------------------------------------------------
    with d_col2:
        st.markdown("#### ✅ 2. PASS 완료 목록")
        st.caption("직접 검수하여 **'PASS(가동중)'**으로 판정된 공장들만 모아둔 파일입니다. 공장명, 전화번호 등 모든 열이 포함되어 있습니다.")
        
        # PASS 데이터만 필터링한 뒤, '검수결과' 컬럼 삭제
        pass_full_df = df[df['검수결과'] == "PASS"]
        df_download_2 = pass_full_df.drop(columns=['검수결과'], errors='ignore')
        
        output2 = io.BytesIO()
        with pd.ExcelWriter(output2, engine='openpyxl') as writer:
            df_download_2.to_excel(writer, index=False, sheet_name='PASS_완료')
        excel_data2 = output2.getvalue()
        
        st.download_button(
            label="다운로드",
            data=excel_data2,
            file_name=f"{original_filename}_2_pass_completed_list.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # ---------------------------------------------------------
    # 3. 우체국용 주소만 있는 파일
    # ---------------------------------------------------------
    with d_col3:
        st.markdown("#### 📮 3. 우체국 업로드용")
        st.caption("PASS 데이터 중에서 DM 발송을 위해 맨 위 제목 열을 지우고, **'우편번호(빈칸)'와 '최종주소'** 딱 두 개 열만 남긴 파일입니다.")
        
        # 3번 파일은 이미 필요한 컬럼 2개만 뽑아내므로 '검수결과' 삭제가 필요 없음
        post_df = pass_full_df[['최종주소']].copy() 
        post_df.insert(0, '우편번호', ' ') 
        
        output3 = io.BytesIO()
        with pd.ExcelWriter(output3, engine='openpyxl') as writer:
            post_df.to_excel(writer, index=False, header=False, sheet_name='우체국업로드')
        excel_data3 = output3.getvalue()
        
        st.download_button(
            label="다운로드",
            data=excel_data3,
            file_name=f"{original_filename}_3_post_upload_list.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )