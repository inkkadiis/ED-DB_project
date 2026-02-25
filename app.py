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

# [디자인 커스텀 영역] CSS 주입
st.markdown("""
<style>
    /* 1. 상단 오른쪽 스트림릿 기본 햄버거 메뉴 숨기기 (깔끔한 사내 툴처럼 보이게) */
    #MainMenu {visibility: hidden;}
    
    /* 2. 맨 아래 'Made with Streamlit' 워터마크 숨기기 */
    footer {visibility: hidden;}
    
    /* 3. 상단 여백(Padding) 확 줄여서 지도를 더 넓게 쓰기 */
    .block-container {
        padding-top: 2.7rem;
        padding-bottom: 2.7rem;
    }
    
    /* 4. 버튼(PASS/폐업) 디자인 바꾸기 (기본 버튼을 예쁘게) */
    .stButton > button, .stLinkButton > a {
        border-radius: 8px; /* 모서리 둥글게 */
        font-weight: bold;  /* 글씨 굵게 */
        transition: 0.3s;   /* 마우스 올렸을 때 애니메이션 */
    }
    
    /* 5. 버튼에 마우스 올렸을 때 테두리 색상 변경 */
    .stButton > button:hover, .stLinkButton > a:hover {
        border-color: #FF4B4B; 
        color: #FF4B4B;
    }
            
    hr {
        margin-top: 1em !important;
        margin-bottom: 1em !important;
    }
            
    [data-testid="column"] [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
    }
</style>
""", unsafe_allow_html=True)

# --- [로그인 기능] ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    login_col1, login_col2 = st.columns([1, 1])
    
    with login_col1:
        st.info("비밀번호를 입력해 주세요.")
        pwd = st.text_input("접속 비밀번호", type="password")
        
        if pwd:
            if pwd == ACCESS_PASSWORD:
                st.session_state.auth = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다. 다시 확인해 주세요.")
                
    st.stop()

# --- [데이터 처리 엔진] ---
@st.cache_data
def load_and_filter(file):
    # 1. 파일 포인터를 맨 앞으로 이동 (스트림릿 안전장치)
    file.seek(0)
    
    # 2. 우선 파일의 첫 줄(header=0)을 기준으로 읽어보기
    if file.name.endswith('.xlsx'):
        df = pd.read_excel(file)
    else:
        df = pd.read_csv(file)
        
    # 3. 💡 스마트 파일 감지기: 다운로드 받은 파일(열 삭제됨) 재업로드 시 처리
    if '최종주소' in df.columns:
        if '검수결과' not in df.columns:
            df['검수결과'] = "미검수" # 재검수를 위해 미검수로 초기화
        return df.reset_index(drop=True)
        
    # 4. 앱을 거치지 않은 완전 원본 양식이라면! (header=1로 올바르게 다시 읽기)
    file.seek(0) 
    if file.name.endswith('.xlsx'):
        df = pd.read_excel(file, header=1)
    else:
        df = pd.read_csv(file, header=1)
    
    # 혹시 모를 엑셀 공백 제거
    df.columns = df.columns.str.strip()
    
    # --- 여기서부터는 원본 파일 전용 클리닝 로직 ---
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
    
    # 3. 주소 정제 함수 (스마트 분리 엔진 적용)
    def clean_addr(row):
        addr = str(row['주소'])
        name = str(row['공장명'])
        
        # 1단계: 괄호 및 '외 x필지' 등 공통 찌꺼기 제거
        base_a = addr
        while re.search(r'\([^()]*\)', base_a):
            base_a = re.sub(r'\([^()]*\)', '', base_a)
        base_a = base_a.replace('(', '').replace(')', '')
        base_a = re.sub(r'외\s?\d?필지.*', '', base_a)
        base_a = re.sub(r'외\s?\d?.*', '', base_a)
        
        # 💡 [신규] 2단계: '검색용'과 '우편물용(최종)' 분리 정제
        
        # 검색용: 콤마(,) 뒤에 오는 층/호수 등 잡다한 상세주소를 날려버림 (지도 검색을 위해)
        clean_search = re.sub(r'[,.\s]*\d+[-~]?\d*호.*', '', base_a) # 404-405호 제거
        clean_search = re.sub(r'[,.\s]*\d+층.*', '', clean_search)    # 3층 제거
        clean_search = re.sub(r',\s*\d+.*', '', clean_search)         # 콤마 뒤 숫자 시작부분 제거
        clean_search = re.sub(r'\s+', ' ', clean_search).strip().rstrip(',')
        
        # 최종용: 우체국 배달을 위해 상세주소(호/층)를 그대로 살려둠
        clean_final = re.sub(r'\s+', ' ', base_a).strip().rstrip(',')
        
        # 공장명 붙이기 옵션 적용 (최종 주소에만)
        final_a = f"{clean_final} {name}" if APPEND_NAME else clean_final
        
        return pd.Series([clean_search, final_a])

# --- [UI 레이아웃] ---

spacer_left, center_col, spacer_right = st.columns([1, 2, 1])

with center_col:
    st.title("전국 공장 DB 검수 시스템")
    uploaded_file = st.file_uploader("공장 DB 파일을 업로드하세요 (CSV 또는 XLSX)", type=['csv', 'xlsx'])

if uploaded_file:
    if "history" not in st.session_state:
        st.session_state.history = []

    if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
        st.session_state.df = load_and_filter(uploaded_file)
        st.session_state.current_file = uploaded_file.name
        st.session_state.history = []
    
    df = st.session_state.df
    
    st.divider()
    
    # 상단 대시보드
    col1, col2, col3, dash_spacer_right = st.columns([0.8, 0.8, 0.8, 1.5])
    
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
            st.write(f"{target_row['최종주소']}")
            
            st.write("---")
            
            # --- [1. PASS 처리 라인] ---
            p_col1, p_col2 = st.columns(2)
            if p_col1.button("✅ PASS (기본)", use_container_width=True):
                st.session_state.history.append(target_idx)
                st.session_state.df.at[target_idx, '검수결과'] = "PASS"
                st.rerun()
                
            if p_col2.button("✂️ PASS (이름제외)", use_container_width=True):
                st.session_state.history.append(target_idx)
                st.session_state.df.at[target_idx, '최종주소'] = target_row['검색용주소']
                st.session_state.df.at[target_idx, '검수결과'] = "PASS"
                st.rerun()
                
            # --- [2. 폐업 및 취소 라인] ---
            a_col1, a_col2 = st.columns(2)
            if a_col1.button("❌ 폐업/철거", use_container_width=True):
                st.session_state.history.append(target_idx)
                st.session_state.df.at[target_idx, '검수결과'] = "폐업"
                st.rerun()
                
            if a_col2.button("⏪ 이전 취소", disabled=len(st.session_state.history)==0, use_container_width=True):
                last_idx = st.session_state.history.pop()
                st.session_state.df.at[last_idx, '검수결과'] = "미검수" 
                st.rerun()
                
            st.write("---")
            
            # --- [3. 중간 저장 (가로 전체 차지)] ---
            output_backup = io.BytesIO()
            with pd.ExcelWriter(output_backup, engine='openpyxl') as writer:
                st.session_state.df.to_excel(writer, index=False, sheet_name='중간저장')
            backup_data = output_backup.getvalue()

            safe_filename = os.path.splitext(st.session_state.current_file)[0]
            
            st.download_button(
                label="💾 진행상황 중간저장",
                data=backup_data,
                file_name=f"{safe_filename}_backup.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
            # --- [4. 💡 외부 지도 검색 링크 (신규 업데이트 분)] ---
            st.write("<br>", unsafe_allow_html=True) # 줄바꿈 공백
            
            search_addr_encoded = urllib.parse.quote(target_row['검색용주소'])
            kakao_url = f"https://map.kakao.com/?q={search_addr_encoded}"
            naver_url = f"https://map.naver.com/p/search/{search_addr_encoded}"
            
            link_col1, link_col2 = st.columns(2)
            with link_col1:
                st.link_button("🟡 카카오맵 보기", url=kakao_url, use_container_width=True)
            with link_col2:
                st.link_button("🟢 네이버맵 보기", url=naver_url, use_container_width=True)
                
        else:
            st.success("🎉 모든 검수가 완료되었습니다!")

    with right_col:
        if not pending_df.empty:
            search_addr = target_row['검색용주소']
            encoded_addr = urllib.parse.quote(search_addr)
            # GitHub Pages 기반 지도 경로
            map_url = f"https://inkkadiis.github.io/ED-DB_project/static/map.html?addr={encoded_addr}&key={KAKAO_JS_KEY}"
            components.iframe(map_url, height=800, scrolling=False)

    # --- [다운로드 섹션] ---
    st.divider()
    
    original_filename = os.path.splitext(st.session_state.current_file)[0]
    spacer_left, d_col1, d_col2, d_col3, d_col4, spacer_right = st.columns([0.5, 1, 1, 1, 1, 0.5], gap="medium")
    
    # 1. 데이터 클리닝이 된 파일
    with d_col1:
        st.markdown("#### 📄 1. 클리닝 원본")
        st.caption("조건에 맞게 필터링되고, 주소 정제가 완료된 **검수 전 전체 원본 데이터**입니다.")
        
        df_download_1 = df.drop(columns=['검수결과'], errors='ignore')
        
        output1 = io.BytesIO()
        with pd.ExcelWriter(output1, engine='openpyxl') as writer:
            df_download_1.to_excel(writer, index=False, sheet_name='클리닝완료_전체')
        excel_data1 = output1.getvalue()
        
        st.download_button(
            label=f"다운로드 ({len(df_download_1)}건)",
            data=excel_data1,
            file_name=f"{original_filename}_1_cleaned_data_master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_btn_1" 
        )
    
    # 2. PASS 된 애들만 모여 있는 파일
    with d_col2:
        st.markdown("#### ✅ 2. PASS 완료")
        st.caption("직접 검수하여 **'PASS(가동중)'**으로 판정된 공장들만 모아둔 파일입니다.")
        
        pass_full_df = df[df['검수결과'] == "PASS"].copy()
        
        if pass_full_df.empty:
            st.info("PASS 처리된 데이터가 없습니다.")
        else:
            df_download_2 = pass_full_df.drop(columns=['검수결과'], errors='ignore')
            
            output2 = io.BytesIO()
            with pd.ExcelWriter(output2, engine='openpyxl') as writer:
                df_download_2.to_excel(writer, index=False, sheet_name='PASS_완료')
            excel_data2 = output2.getvalue()
            
            st.download_button(
                label=f"다운로드 ({len(df_download_2)}건)",
                data=excel_data2,
                file_name=f"{original_filename}_2_pass_list.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_2"
            )
    
    # 3. 우체국용 주소만 있는 파일
    with d_col3:
        st.markdown("#### 📮 3. 우체국용")
        st.caption("DM 발송을 위해 **'우편번호(빈칸)'와 '최종주소'** 딱 두 개 열만 남긴 파일입니다.")
        
        pass_full_df = df[df['검수결과'] == "PASS"].copy()
        
        if pass_full_df.empty:
            st.info("PASS 처리된 데이터가 없습니다.")
        else:
            post_df = pass_full_df[['최종주소']].copy() 
            post_df.insert(0, '우편번호', ' ') 
            
            output3 = io.BytesIO()
            with pd.ExcelWriter(output3, engine='openpyxl') as writer:
                post_df.to_excel(writer, index=False, header=False, sheet_name='우체국업로드')
            excel_data3 = output3.getvalue()
            
            st.download_button(
                label=f"다운로드 ({len(post_df)}건)",
                data=excel_data3,
                file_name=f"{original_filename}_3_post_upload.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_3"
            )

    # 4. ❌ 폐업 및 제외 대상 파일
    with d_col4:
        st.markdown("#### ❌ 4. 제외 목록")
        st.caption("검수 과정에서 **'폐업/철거'** 등으로 판정되어 타겟에서 제외된 공장들만 모아둔 파일입니다.")
        
        fail_df = df[df['검수결과'] == "폐업"].copy()
        
        if fail_df.empty:
            st.info("제외 처리된 데이터가 없습니다.")
        else:
            df_download_4 = fail_df.drop(columns=['검수결과'], errors='ignore')
            
            output4 = io.BytesIO()
            with pd.ExcelWriter(output4, engine='openpyxl') as writer:
                df_download_4.to_excel(writer, index=False, sheet_name='제외_목록')
            excel_data4 = output4.getvalue()
            
            st.download_button(
                label=f"다운로드 ({len(df_download_4)}건)",
                data=excel_data4,
                file_name=f"{original_filename}_4_excluded_list.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_4"
            )