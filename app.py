"""
전국 공장 DB 검수 시스템
Factory Database Inspection System
"""

import streamlit as st
import pandas as pd
import re
import os
import io
from dotenv import load_dotenv
import streamlit.components.v1 as components
import urllib.parse
from typing import Optional, Tuple

# ==========================================
# 환경 설정 로드
# ==========================================
load_dotenv()
KAKAO_JS_KEY = os.getenv("KAKAO_JS_KEY")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

# ==========================================
# 필터링 및 정제 규칙
# ==========================================
MIN_EMPLOYEES = 15       # 최소 종업원수
MAX_EMPLOYEES = 300      # 최대 종업원수
INDUSTRY_MIN = 10        # 산업코드 시작
INDUSTRY_MAX = 34        # 산업코드 끝
APPEND_NAME = True       # 주소 뒤에 공장명 붙일지 여부

# 필수 컬럼 정의
REQUIRED_COLUMNS = ['공장명', '주소', '종업원수', '기업구분', '업종코드']
PROCESSED_MARKER = '최종주소'  # 이미 처리된 파일 감지용

# 검수 상태 정의
STATUS_PENDING = "미검수"
STATUS_PASS = "PASS"
STATUS_CLOSED = "폐업"

# ==========================================
# Streamlit 페이지 설정
# ==========================================
st.set_page_config(
    layout="wide",
    page_title="전국 공장 DB 검수기",
    page_icon="🏭"
)

# ==========================================
# 커스텀 CSS 스타일
# ==========================================
st.markdown("""
<style>
    /* 기본 UI 요소 숨기기 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 레이아웃 최적화 */
    .block-container {
        padding-top: 2.7rem;
        padding-bottom: 2.7rem;
    }
    
    /* 버튼 스타일링 */
    .stButton > button, .stLinkButton > a {
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover, .stLinkButton > a:hover {
        border-color: #FF4B4B;
        color: #FF4B4B;
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    /* 구분선 스타일 - 축소 */
    hr {
        margin-top: 0.3em !important;
        margin-bottom: 0.3em !important;
    }
    
    /* 컬럼 간격 조정 */
    [data-testid="column"] [data-testid="stVerticalBlock"] {
        gap: 0.1rem !important;
    }
    
    /* 메트릭 카드 스타일 개선 */
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
    
    /* 헤더 여백 축소 */
    h5 {
        margin-top: 0.5rem !important;
        margin-bottom: 0.3rem !important;
    }
    
    /* 버튼 패딩 축소 */
    .stButton > button {
        padding: 0.25rem 0.5rem !important;
    }
    
    /* 텍스트 영역 여백 축소 */
    .stTextArea > div > div {
        padding: 0.25rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 유틸리티 함수들
# ==========================================

def validate_environment() -> bool:
    """환경 변수 검증"""
    if not KAKAO_JS_KEY:
        st.error("⚠️ KAKAO_JS_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return False
    if not ACCESS_PASSWORD:
        st.error("⚠️ ACCESS_PASSWORD가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return False
    return True


def validate_dataframe(df: pd.DataFrame) -> Tuple[bool, str]:
    """데이터프레임 유효성 검사"""
    # 이미 처리된 파일인지 확인
    if PROCESSED_MARKER in df.columns:
        return True, "processed"
    
    # 필수 컬럼 확인
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"필수 컬럼이 누락되었습니다: {', '.join(missing_cols)}"
    
    return True, "original"


def check_industry_code(code) -> bool:
    """산업코드 유효성 검사"""
    if pd.isna(code):
        return False
    try:
        code_str = str(code).split(',')[0].strip()[:2]
        if not code_str.isdigit():
            return False
        code_num = int(code_str)
        return INDUSTRY_MIN <= code_num <= INDUSTRY_MAX
    except (ValueError, IndexError):
        return False


def clean_address(row: pd.Series) -> pd.Series:
    """주소 정제 및 분리 (검색용/최종용)"""
    addr = str(row['주소'])
    name = str(row['공장명'])
    
    # 1단계: 괄호 및 불필요한 문자 제거
    base_addr = addr
    # 중첩 괄호 제거
    while re.search(r'\([^()]*\)', base_addr):
        base_addr = re.sub(r'\([^()]*\)', '', base_addr)
    
    base_addr = base_addr.replace('(', '').replace(')', '')
    base_addr = re.sub(r'외\s?\d*필지.*', '', base_addr)
    base_addr = re.sub(r'외\s?\d*.*', '', base_addr)
    
    # 2단계: 검색용 주소 (상세주소 제거)
    search_addr = base_addr
    search_addr = re.sub(r'[,.\s]*\d+[-~]?\d*호.*', '', search_addr)
    search_addr = re.sub(r'[,.\s]*\d+층.*', '', search_addr)
    search_addr = re.sub(r',\s*\d+.*', '', search_addr)
    search_addr = re.sub(r'\s+', ' ', search_addr).strip().rstrip(',')
    
    # 3단계: 최종용 주소 (상세주소 유지)
    final_addr = re.sub(r'\s+', ' ', base_addr).strip().rstrip(',')
    
    # 공장명 붙이기 옵션 적용
    if APPEND_NAME:
        final_addr = f"{final_addr} {name}"
    
    return pd.Series([search_addr, final_addr])


def load_and_filter(file) -> Optional[pd.DataFrame]:
    """파일 로드 및 필터링 처리"""
    try:
        file.seek(0)
        
        # 파일 형식에 따라 읽기
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            df = pd.read_csv(file, encoding='utf-8-sig')
        
        # 첫 번째 읽기 시도 정보 표시
        st.info(f"📊 파일 정보: {len(df)}행 x {len(df.columns)}열 감지됨")
        
        # 데이터프레임 검증
        is_valid, status = validate_dataframe(df)
        
        if not is_valid:
            st.warning(f"⚠️ 첫 번째 행을 헤더로 읽기 실패. 두 번째 행을 헤더로 재시도합니다...")
            
            # 원본 파일 처리 (header=1로 재시도)
            file.seek(0)
            if file.name.endswith('.xlsx'):
                df = pd.read_excel(file, header=1, engine='openpyxl')
            else:
                df = pd.read_csv(file, header=1, encoding='utf-8-sig')
            
            # 컬럼명 정리
            df.columns = df.columns.str.strip()
            
            st.info(f"📊 재읽기 결과: {len(df)}행 x {len(df.columns)}열")
            st.info(f"🔍 감지된 컬럼: {', '.join(df.columns.tolist()[:10])}{'...' if len(df.columns) > 10 else ''}")
            
            # 재검증
            is_valid, status = validate_dataframe(df)
            if not is_valid:
                st.error(f"❌ 파일 검증 실패: {status}")
                st.error(f"📋 현재 컬럼: {list(df.columns)[:10]}")
                return None
        
        # 이미 처리된 파일인 경우
        if status == "processed":
            if '검수결과' not in df.columns:
                df['검수결과'] = STATUS_PENDING
            st.success(f"✅ 이전 작업 파일을 불러왔습니다 ({len(df):,}건)")
            return df.reset_index(drop=True)
        
        # 데이터 필터링
        with st.spinner('📊 데이터 필터링 중...'):
            initial_count = len(df)
            
            # 1. 종업원수 필터링
            df['종업원수'] = pd.to_numeric(df['종업원수'], errors='coerce')
            before_employee_filter = len(df)
            df = df[(df['종업원수'] >= MIN_EMPLOYEES) & (df['종업원수'] <= MAX_EMPLOYEES)]
            after_employee_filter = len(df)
            
            # 2. 기업구분 필터링
            before_company_filter = len(df)
            df = df[df['기업구분'].str.contains('소기업|중기업', na=False, regex=True)]
            after_company_filter = len(df)
            
            # 3. 산업코드 필터링
            before_industry_filter = len(df)
            df = df[df['업종코드'].apply(check_industry_code)]
            filtered_count = len(df)
            
            # 필터링 결과 상세 표시
            st.info(f"""
            **📊 필터링 결과:**
            - 원본 데이터: {initial_count:,}건
            - 종업원수 필터링 ({MIN_EMPLOYEES}~{MAX_EMPLOYEES}명): {before_employee_filter:,}건 → {after_employee_filter:,}건 ({before_employee_filter - after_employee_filter:,}건 제외)
            - 기업구분 필터링 (소/중기업): {before_company_filter:,}건 → {after_company_filter:,}건 ({before_company_filter - after_company_filter:,}건 제외)
            - 산업코드 필터링 ({INDUSTRY_MIN}~{INDUSTRY_MAX}): {before_industry_filter:,}건 → {filtered_count:,}건 ({before_industry_filter - filtered_count:,}건 제외)
            - **최종 결과: {filtered_count:,}건**
            """)
            
            if filtered_count == 0:
                st.error("⚠️ 필터링 조건에 맞는 데이터가 없습니다. 필터링 설정을 확인해주세요.")
                return None
        
        # 주소 정제
        with st.spinner('🏠 주소 정제 중...'):
            df[['검색용주소', '최종주소']] = df.apply(clean_address, axis=1)
        
        # 검수결과 초기화
        df['검수결과'] = STATUS_PENDING
        
        # 가나다순 정렬 (검색용주소 기준)
        df = df.sort_values(by='검색용주소').reset_index(drop=True)
        st.success("✅ 주소 가나다순 정렬 완료")
        
        return df
        
    except Exception as e:
        st.error(f"❌ 파일 처리 중 오류가 발생했습니다: {str(e)}")
        return None


def create_excel_download(df: pd.DataFrame, sheet_name: str = 'Sheet1') -> bytes:
    """엑셀 파일 생성"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def get_progress_stats(df: pd.DataFrame) -> dict:
    """진행 상황 통계 계산"""
    total = len(df)
    done = len(df[df['검수결과'] != STATUS_PENDING])
    pass_cnt = len(df[df['검수결과'] == STATUS_PASS])
    closed_cnt = len(df[df['검수결과'] == STATUS_CLOSED])
    progress = int(done / total * 100) if total > 0 else 0
    
    return {
        'total': total,
        'done': done,
        'pass': pass_cnt,
        'closed': closed_cnt,
        'progress': progress
    }


# ==========================================
# 인증 시스템
# ==========================================

if not validate_environment():
    st.stop()

if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.markdown("### 🔐 로그인")
    login_col1, login_col2 = st.columns([1, 1])
    
    with login_col1:
        st.info("비밀번호를 입력해주세요.")
        pwd = st.text_input("접속 비밀번호", type="password", key="login_pwd")
        
        if pwd:
            if pwd == ACCESS_PASSWORD:
                st.session_state.auth = True
                st.success("✅ 인증 성공!")
                st.rerun()
            else:
                st.error("❌ 비밀번호가 일치하지 않습니다.")
    
    st.stop()

# ==========================================
# 메인 UI
# ==========================================

# 헤더
spacer_left, center_col, spacer_right = st.columns([1, 2, 1])
with center_col:
    st.title("전국 공장 DB 검수 시스템")
    uploaded_file = st.file_uploader(
        "공장 DB 파일을 업로드하세요",
        type=['csv', 'xlsx'],
        help="CSV 또는 XLSX 형식의 파일을 업로드해주세요."
    )

# 파일 업로드 처리
if uploaded_file:
    # 세션 상태 초기화
    if "history" not in st.session_state:
        st.session_state.history = []
    
    # 새 파일 업로드 시 처리
    if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
        with st.spinner('⏳ 파일 처리 중...'):
            st.session_state.df = load_and_filter(uploaded_file)
            st.session_state.current_file = uploaded_file.name
            st.session_state.history = []
    
    df = st.session_state.df
    
    # 데이터 유효성 확인
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.warning("⚠️ 유효한 데이터가 없습니다. 파일을 다시 업로드해주세요.")
        if "current_file" in st.session_state:
            del st.session_state["current_file"]
        st.stop()
    
    st.divider()
    
    # ==========================================
    # 대시보드
    # ==========================================
    stats = get_progress_stats(df)
    
    col1, col2, col3, col4, dash_spacer = st.columns([1, 1, 1, 1, 1])
    
    col1.metric("📊 전체 타겟", f"{stats['total']:,}건")
    col2.metric("⏳ 검수 진행", f"{stats['done']:,}건", f"{stats['progress']}%")
    col3.metric("✅ PASS", f"{stats['pass']:,}건")
    col4.metric("❌ 폐업", f"{stats['closed']:,}건")
    
    # 진행률 바
    if stats['total'] > 0:
        st.progress(stats['progress'] / 100)
    
    st.divider()
    
    # ==========================================
    # 작업 영역
    # ==========================================
    left_col, right_col = st.columns([1, 2])
    
    with left_col:
        st.subheader("검수 리스트")
        
        pending_df = df[df['검수결과'] == STATUS_PENDING]
        
        if not pending_df.empty:
            target_idx = pending_df.index[0]
            target_row = df.iloc[target_idx]
            
            # 현재 검수 대상 정보
            remaining = len(pending_df)
            st.info(f"**{target_row['공장명']}** (남은 검수: {remaining:,}건)")
            st.markdown(f"📍 {target_row['최종주소']}")
            
            # 추가 정보 (있는 경우)
            if '종업원수' in target_row:
                st.caption(f"👥 종업원수: {target_row['종업원수']}명")
            
            st.write("---")
            
            # 2x2 그리드 레이아웃
            # 첫 번째 행: PASS (좌) | 검수제외 (우)
            row1_col1, row1_col2 = st.columns(2)
            
            with row1_col1:
                st.markdown("##### PASS")
                st.caption("업체명과 지도상 업체명이 다르거나 한 주소내에 많은 업체가 있는 경우, 외부지도로 확인 후 이름제외 버튼 활용")
                
                if st.button("✅ 기본 주소", use_container_width=True, key="pass_default"):
                    st.session_state.history.append(target_idx)
                    st.session_state.df.at[target_idx, '검수결과'] = STATUS_PASS
                    st.rerun()
                
                if st.button("✂️ 이름 제외", use_container_width=True, key="pass_no_name"):
                    st.session_state.history.append(target_idx)
                    st.session_state.df.at[target_idx, '최종주소'] = target_row['검색용주소']
                    st.session_state.df.at[target_idx, '검수결과'] = STATUS_PASS
                    st.rerun()
            
            with row1_col2:
                st.markdown("##### 검수제외")
                st.caption("폐업/철거 클릭 후 추후에 재차 확인 가능")
                st.write("")
                st.write("")
                st.write("")  # 빈 공간 추가하여 버튼 위치 맞춤
                
                if st.button("❌ 폐업/철거", use_container_width=True, key="btn_closed"):
                    st.session_state.history.append(target_idx)
                    st.session_state.df.at[target_idx, '검수결과'] = STATUS_CLOSED
                    st.rerun()
                
                if st.button("⏪ 이전 취소",
                           disabled=len(st.session_state.history) == 0,
                           use_container_width=True,
                           key="btn_undo"):
                    last_idx = st.session_state.history.pop()
                    st.session_state.df.at[last_idx, '검수결과'] = STATUS_PENDING
                    st.rerun()
            
            # 두 번째 행: 저장 (좌) | 외부지도 (우)
            row2_col1, row2_col2 = st.columns(2)
            
            with row2_col1:
                st.markdown("##### 저장")
                backup_data = create_excel_download(st.session_state.df, '중간저장')
                safe_filename = os.path.splitext(st.session_state.current_file)[0]
                
                st.download_button(
                    label="💾 중간저장",
                    data=backup_data,
                    file_name=f"{safe_filename}_backup.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="btn_backup"
                )
            
            with row2_col2:
                st.markdown("##### 외부지도")
                search_addr_encoded = urllib.parse.quote(target_row['검색용주소'])
                
                st.link_button(
                    "🟡 카카오",
                    url=f"https://map.kakao.com/?q={search_addr_encoded}",
                    use_container_width=True
                )
                
                st.link_button(
                    "🟢 네이버",
                    url=f"https://map.naver.com/p/search/{search_addr_encoded}",
                    use_container_width=True
                )
            
            # 주소 수정 섹션
            st.markdown("##### 주소수정")
            
            # 주소 수정 입력란
            edited_address = st.text_area(
                "최종주소",
                value=target_row['최종주소'],
                height=60,
                key=f"addr_edit_{target_idx}",
                label_visibility="collapsed"
            )
            
            # 주소 저장 버튼
            addr_col1, addr_col2 = st.columns(2)
            
            if addr_col1.button("💾 저장", use_container_width=True, key="btn_save_addr"):
                if edited_address.strip() and edited_address != target_row['최종주소']:
                    st.session_state.df.at[target_idx, '최종주소'] = edited_address.strip()
                    st.success("저장완료")
                    st.rerun()
                elif not edited_address.strip():
                    st.error("주소입력 필요")
                else:
                    st.info("변경없음")
            
            if addr_col2.button("🔄 복구", use_container_width=True, key="btn_reset_addr"):
                st.session_state.df.at[target_idx, '최종주소'] = target_row['검색용주소'] + (' ' + target_row['공장명'] if APPEND_NAME else '')
                st.success("복구완료")
                st.rerun()
        
        else:
            st.success("🎉 축하합니다! 모든 검수가 완료되었습니다!")
            st.balloons()
    
    # 지도 영역
    with right_col:
        if not pending_df.empty:
            search_addr = target_row['검색용주소']
            encoded_addr = urllib.parse.quote(search_addr)
            map_url = f"https://inkkadiis.github.io/ED-DB_project/static/map.html?addr={encoded_addr}&key={KAKAO_JS_KEY}"
            components.iframe(map_url, height=800, scrolling=False)
        else:
            st.info("🗺️ 검수할 항목이 없습니다.")
    
    # ==========================================
    # 다운로드 섹션
    # ==========================================
    st.divider()
    st.subheader("데이터 다운로드")
    
    original_filename = os.path.splitext(st.session_state.current_file)[0]
    d_col1, d_col2, d_col3, d_col4 = st.columns(4, gap="medium")
    
    # 1. 클리닝 원본
    with d_col1:
        st.markdown("##### 클리닝 원본")
        st.caption("필터링 및 정제 완료된 전체 데이터")
        
        df_download_1 = df.drop(columns=['검수결과'], errors='ignore')
        excel_data1 = create_excel_download(df_download_1, '클리닝완료_전체')
        
        st.download_button(
            label=f"다운로드 ({len(df_download_1):,}건)",
            data=excel_data1,
            file_name=f"{original_filename}_1_cleaned.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_btn_1"
        )
    
    # 2. PASS 목록
    with d_col2:
        st.markdown("##### PASS 목록")
        st.caption("검수 완료된 가동중인 공장")
        
        pass_df = df[df['검수결과'] == STATUS_PASS].copy()
        
        if pass_df.empty:
            st.info("데이터 없음")
        else:
            df_download_2 = pass_df.drop(columns=['검수결과'], errors='ignore')
            excel_data2 = create_excel_download(df_download_2, 'PASS_완료')
            
            st.download_button(
                label=f"다운로드 ({len(df_download_2):,}건)",
                data=excel_data2,
                file_name=f"{original_filename}_2_pass.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_2"
            )
    
    # 3. 우체국용
    with d_col3:
        st.markdown("##### 우체국용")
        st.caption("우편번호 + 주소 형식")
        
        pass_df = df[df['검수결과'] == STATUS_PASS].copy()
        
        if pass_df.empty:
            st.info("데이터 없음")
        else:
            post_df = pass_df[['최종주소']].copy()
            post_df.insert(0, '우편번호', ' ')
            
            excel_data3 = create_excel_download(post_df, '우체국업로드')
            
            st.download_button(
                label=f"다운로드 ({len(post_df):,}건)",
                data=excel_data3,
                file_name=f"{original_filename}_3_post.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_3"
            )
    
    # 4. 제외 목록
    with d_col4:
        st.markdown("##### 제외 목록")
        st.caption("폐업/철거로 제외된 공장")
        
        closed_df = df[df['검수결과'] == STATUS_CLOSED].copy()
        
        if closed_df.empty:
            st.info("데이터 없음")
        else:
            df_download_4 = closed_df.drop(columns=['검수결과'], errors='ignore')
            excel_data4 = create_excel_download(df_download_4, '제외_목록')
            
            st.download_button(
                label=f"다운로드 ({len(df_download_4):,}건)",
                data=excel_data4,
                file_name=f"{original_filename}_4_excluded.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_btn_4"
            )

else:
    # 파일 미업로드 시 안내
    st.info("👆 파일을 업로드하여 검수를 시작하세요.")
    
    with st.expander("📖 사용 방법"):
        st.markdown("""
        ### 사용 방법
        
        1. **파일 업로드**: 공장 DB 파일(CSV 또는 XLSX)을 업로드합니다.
        2. **자동 필터링**: 설정된 조건에 따라 자동으로 데이터가 필터링됩니다.
        3. **지도 검수**: 각 공장의 위치를 지도에서 확인하며 검수합니다.
        4. **검수 처리**: PASS 또는 폐업/철거로 분류합니다.
        5. **데이터 다운로드**: 검수 완료 후 필요한 형식으로 다운로드합니다.
        
        ### 필터링 조건
        - 종업원수: {MIN_EMPLOYEES}명 ~ {MAX_EMPLOYEES}명
        - 기업구분: 소기업, 중기업
        - 산업코드: {INDUSTRY_MIN} ~ {INDUSTRY_MAX}
        """.format(
            MIN_EMPLOYEES=MIN_EMPLOYEES,
            MAX_EMPLOYEES=MAX_EMPLOYEES,
            INDUSTRY_MIN=INDUSTRY_MIN,
            INDUSTRY_MAX=INDUSTRY_MAX
        ))
