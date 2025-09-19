# 🔐 라이브러리 및 기본 설정
import discord
from discord.ext import commands
from discord.ui import Button, View
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import random
import os
import json
import sys
import re
import asyncio

KST = timezone(timedelta(hours=9))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 🔐 환경변수 확인
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
SHEET_KEY = os.getenv("SHEET_KEY")

missing = [k for k, v in {
    "DISCORD_BOT_TOKEN": DISCORD_TOKEN,
    "GOOGLE_CREDS": GOOGLE_CREDS,
    "SHEET_KEY": SHEET_KEY
}.items() if not v]
if missing:
    print(f"❌ 누락된 환경변수: {', '.join(missing)}")
    sys.exit(1)

# 🔐 구글 시트 인증
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
try:
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gclient = gspread.authorize(creds)
except Exception as e:
    print("❌ 구글 스프레드시트 인증/접속 실패:", e)
    sys.exit(1)

# 🔧 시트 핸들러 유틸 (누락 보완)
def ws(title: str):
    """같은 문서 내 워크시트 핸들러"""
    return gclient.open_by_key(SHEET_KEY).worksheet(title)

# 🧰 유틸
def now_kst_str(fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.now(KST).strftime(fmt)

DICE_EMOJI = {
    1: "🎲1", 2: "🎲2", 3: "🎲3",
    4: "🎲4", 5: "🎲5", 6: "🎲6"
}

# 다중 이름 파서: 공백/쉼표 섞여도 처리 (기존 사용처 유지)
def _parse_names_and_amount(args):
    """
    args 예: ("홍길동","김철수","5")  또는 ("홍길동,김철수","5")
    returns: (names:list[str], amount:int)  또는 (None, error_msg)
    """
    if len(args) < 2:
        return None, "⚠️ 최소 1명 이상의 이름과 수치를 입력하세요. 예) `!추가 홍길동 김철수 5`"

    amount_str = args[-1]
    if not amount_str.isdigit():
        return None, "⚠️ 수치는 양의 정수여야 합니다. 예) `!추가 홍길동 김철수 5`"
    amount = int(amount_str)

    raw_names = args[:-1]
    names = []
    for token in raw_names:
        for part in token.split(","):
            nm = part.strip()
            if nm:
                names.append(nm)

    if not names:
        return None, "⚠️ 유효한 이름이 없습니다. 예) `!추가 홍길동 김철수 5`"

    # 같은 이름이 여러 번 입력되면 중복 제거(순서 유지)
    names = list(dict.fromkeys(names))
    return (names, amount), None

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user} ({bot.user.id})')

@bot.command(name="접속", help="현재 봇이 정상 작동 중인지 확인합니다. 예) !접속")
async def 접속(ctx):
    await ctx.send(f"현재 봇이 구동 중입니다.\n{now_kst_str()}")

# ✅ 연결 테스트용 커맨드 (원하면 삭제 가능)
@bot.command(name="시트테스트", help="연결 확인 시트의 A1에 현재 시간을 기록하고 값을 확인합니다. 예) !시트테스트")
async def 시트테스트(ctx):
    try:
        sh = ws("연결 확인")  # '연결 확인' 시트 핸들러
        sh.update_acell("A1", f"✅ 연결 OK @ {now_kst_str()}")
        val = sh.acell("A1").value
        await ctx.send(f"A1 = {val}")
    except Exception as e:
        await ctx.send(f"❌ 시트 접근 실패: {e}")

# ✅ 다이스 버튼
class DiceButton(Button):
    def __init__(self, sides: int, style: discord.ButtonStyle, owner_id: int):
        super().__init__(label=f"1d{sides}", style=style)
        self.sides = sides
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        # 버튼 제한: 명령어 사용한 사람만
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "이 버튼은 명령어를 사용한 사람만 누를 수 있어요.", ephemeral=True
            )
            return

        roll = random.randint(1, self.sides)
        await interaction.response.send_message(
            f"{interaction.user.mention}의 **1d{self.sides}** 결과: **{roll}**\n{now_kst_str()}"
        )

class DiceView(View):
    def __init__(self, owner_id: int, timeout: int = 60):
        super().__init__(timeout=timeout)
        # 버튼 색: 빨강(위험)=1d6, 파랑(기본)=1d10, 초록(성공)=1d100
        self.add_item(DiceButton(6,   discord.ButtonStyle.danger,  owner_id))
        self.add_item(DiceButton(10,  discord.ButtonStyle.primary, owner_id))
        self.add_item(DiceButton(100, discord.ButtonStyle.success, owner_id))
        self.message = None

    async def on_timeout(self):
        # 타임아웃 시 버튼 비활성화
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

@bot.command(name="다이스", help="버튼으로 1d6/1d10/1d100을 굴립니다. 예) !다이스")
async def 다이스(ctx):
    view = DiceView(owner_id=ctx.author.id)
    msg = await ctx.send(f"{ctx.author.mention} 굴릴 주사위를 선택하세요:", view=view)
    view.message = msg

# ─────────────────────────────────────────────────────────
# ✅ 추가: !군번 / !추첨 / !랜덤 (통일된 [결과] 포맷)
# ─────────────────────────────────────────────────────────

# ===== 군번(72******) 부여/재발급 — 수식 제거 + 텍스트 고정 =====
import re

def _find_row_by_exact_name_colB(sh, target: str) -> int | None:
    """'군번' 시트 B열에서 2행부터 '정확 일치' 행 번호 반환(헤더 제외)."""
    tgt = (target or "").strip()
    if not tgt:
        return None
    # 1) 정규식 정확일치로 시도
    try:
        cell = sh.find(f"^{re.escape(tgt)}$", in_column=2, case_sensitive=True, regex=True)
        if cell and cell.row >= 2:
            return cell.row
    except Exception:
        pass
    # 2) 수동 스캔 (2행부터)
    col_vals = sh.col_values(2)
    for idx, val in enumerate(col_vals[1:], start=2):
        if (val or "").strip() == tgt:
            return idx
    return None

def _gunbeon_existing_set(sh):
    """D열 기존 군번(공백 제외) 집합."""
    return {v.strip() for v in sh.col_values(4) if v and v.strip()}

def _gen_unique_gunbeon(existing: set, max_tries=2000) -> str | None:
    """기존과 중복되지 않는 72****** 생성."""
    for _ in range(max_tries):
        cand = f"72{random.randint(0, 999999):06d}"
        if cand not in existing:
            return cand
    return None

@bot.command(
    name="군번",
    help="!군번 이름 [강제|--force|force|재발급] → '군번' 시트 B열에서 이름을 찾아 D열에 고유 군번(72******)을 기입합니다."
)
async def 군번(ctx, 이름: str, 옵션: str = ""):
    try:
        sh = ws("군번")
        row = _find_row_by_exact_name_colB(sh, 이름)
        if not row:
            await ctx.send(f"[결과]\n❌ '군번' 시트 B열에서 '{이름}'을(를) 찾지 못했습니다.\n{now_kst_str()}")
            return

        current = (sh.cell(row, 4).value or "").strip()   # D열 현재 값
        force = (옵션 or "").strip().lower() in {"강제", "--force", "force", "재발급"}
        if current and not force:
            await ctx.send(f"[결과]\nℹ️ '{이름}'은(는) 이미 군번 `{current}`가 있습니다.\n{now_kst_str()}")
            return

        # 중복 방지 집합 준비
        existing = _gunbeon_existing_set(sh)
        if current in existing:
            existing.remove(current)

        new_id = _gen_unique_gunbeon(existing)
        if not new_id:
            await ctx.send(f"[결과]\n❌ 군번 생성 실패: 잠시 후 다시 시도해 주세요.\n{now_kst_str()}")
            return

        # ===== 핵심: 해당 D{row} 셀의 수식을 제거하고 TEXT 형식으로 값을 '고정' =====
        doc = gclient.open_by_key(SHEET_KEY)
        ws_obj = doc.worksheet("군번")
        sheet_id = ws_obj._properties.get("sheetId")

        requests = []

        # (A) D열 전체를 TEXT 포맷으로 고정 (자동 숫자/전화번호 변환 방지)
        if sheet_id is not None:
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startColumnIndex": 3,  # D (0-based)
                        "endColumnIndex": 4
                    },
                    "cell": {
                        "userEnteredFormat": {"numberFormat": {"type": "TEXT"}}
                    },
                    "fields": "userEnteredFormat.numberFormat"
                }
            })

            # (B) 대상 셀(D{row})의 기존 수식/값 제거
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 3,
                        "endColumnIndex": 4
                    },
                    "fields": "userEnteredValue"
                }
            })

            # (C) 대상 셀(D{row})에 텍스트로 값 쓰기
            requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 3,
                        "endColumnIndex": 4
                    },
                    "rows": [{
                        "values": [{
                            "userEnteredValue": {"stringValue": new_id}
                        }]
                    }],
                    "fields": "userEnteredValue"
                }
            })

            doc.batch_update({"requests": requests})
        else:
            # sheetId를 못얻은 예외적 상황: RAW로 직접 기록(대부분 충분)
            sh.update(f"D{row}", [[new_id]], value_input_option="RAW")

        # 최종 수정자 기록(실패 무시)
        try:
            sh.update_acell("I13", getattr(ctx.author, "display_name", "unknown"))
        except Exception as e:
            print(f"[WARN] I13 갱신 실패: {e}")

        # 응답
        if force and current:
            await ctx.send(f"[결과]\n✅ '{이름}' 군번 재발급 완료: `{current}` → `{new_id}`\n{now_kst_str()}")
        else:
            await ctx.send(f"[결과]\n✅ '{이름}'에게 군번 `{new_id}` 부여 완료.\n{now_kst_str()}")

    except Exception as e:
        await ctx.send(f"[결과]\n❌ 군번 처리 실패: {e}\n{now_kst_str()}")

@bot.command(name="추첨", help="!추첨 숫자 → '군번' 시트 B6 이후 이름 중에서 무작위 추첨")
async def 추첨(ctx, 숫자: str):
    if not 숫자.isdigit():
        await ctx.send(f"[결과]\n⚠️ 숫자를 입력하세요. 예) `!추첨 3`\n{now_kst_str()}")
        return
    k = int(숫자)
    if k <= 0:
        await ctx.send(f"[결과]\n⚠️ 1 이상의 숫자를 입력하세요.\n{now_kst_str()}")
        return
    try:
        sh = ws("군번")
        colB = sh.col_values(2)
        candidates = [v.strip() for v in colB[5:] if v and v.strip()]  # B6~
        total = len(candidates)
        if total == 0:
            await ctx.send(f"[결과]\n⚠️ 추첨 대상이 없습니다. (B6 이후가 비어 있음)\n{now_kst_str()}")
            return
        if k > total:
            await ctx.send(f"[결과]\n⚠️ 추첨 인원이 대상 수({total}명)를 초과합니다.\n{now_kst_str()}")
            return
        winners = random.sample(candidates, k)
        await ctx.send(f"[결과]\n추첨 결과 ({k}명): {', '.join(winners)}\n{now_kst_str()}")
    except Exception as e:
        await ctx.send(f"[결과]\n❌ 추첨 실패: {e}\n{now_kst_str()}")

def _parse_names_and_k_for_random(args):
    if len(args) < 2:
        return None, "⚠️ 최소 1명 이상의 이름과 추첨 인원 수를 입력하세요."
    k_str = args[-1]
    if not k_str.isdigit():
        return None, "⚠️ 추첨 인원 수는 정수여야 합니다."
    k = int(k_str)
    if k <= 0:
        return None, "⚠️ 추첨 인원 수는 1 이상이어야 합니다."
    raw_names = args[:-1]
    names = []
    for token in raw_names:
        for part in token.split(","):
            nm = part.strip()
            if nm:
                names.append(nm)
    names = list(dict.fromkeys(names))  # 중복 제거
    return (names, k), None

@bot.command(
    name="랜덤",
    help="!랜덤 이름1 이름2 ... k → 입력한 이름 중 서로 다른 k명을 무작위로 뽑습니다."
)
async def 랜덤(ctx, *args):
    parsed, err = _parse_names_and_k_for_random(args)
    if err:
        await ctx.send(f"[결과]\n{err}\n{now_kst_str()}")
        return
    names, k = parsed
    n = len(names)
    if k > n:
        k = n
    winners = random.sample(names, k)
    await ctx.send(f"[결과]\n랜덤 선택 ({k}명): {', '.join(winners)}\n{now_kst_str()}")

# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
