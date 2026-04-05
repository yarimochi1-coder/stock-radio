"""
株式投資ラジオ 自動生成スクリプト

使い方:
  python generate_radio.py

必要な環境変数:
  ANTHROPIC_API_KEY       — Claude APIキー
  LINE_CHANNEL_TOKEN      — LINE Messaging APIアクセストークン
  LINE_USER_ID            — 送信先のLINE User ID
"""

import os
import sys
import json
import asyncio
import requests
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
RULES_PATH = SCRIPT_DIR / "rules" / "台本生成ルール.md"
CURRICULUM_PATH = SCRIPT_DIR / "カリキュラム" / "curriculum.json"
PROGRESS_PATH = SCRIPT_DIR / "カリキュラム" / "progress.json"
SCRIPT_OUTPUT_DIR = SCRIPT_DIR / "台本"
AUDIO_DIR = SCRIPT_DIR / "音声"

TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_JP = datetime.now().strftime("%Y年%m月%d日")

TTS_VOICE = "ja-JP-NanamiNeural"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
IS_CI = os.environ.get("CI") == "true"


# ---------------------------------------------------------------------------
# 進捗管理
# ---------------------------------------------------------------------------
def get_current_day() -> int:
    """現在のレッスンDay番号を取得。初回は1から開始。"""
    if PROGRESS_PATH.exists():
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        return progress.get("current_day", 1)
    return 1


def save_progress(day: int):
    """進捗を保存"""
    progress = {
        "current_day": day + 1,
        "last_completed_day": day,
        "last_completed_date": TODAY,
    }
    PROGRESS_PATH.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_lesson(day: int) -> dict | None:
    """カリキュラムからレッスン情報を取得"""
    curriculum = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
    for phase in curriculum["phases"]:
        for lesson in phase["lessons"]:
            if lesson["day"] == day:
                return {
                    **lesson,
                    "phase_title": phase["title"],
                    "phase_num": phase["phase"],
                }
    return None


def get_next_lesson_title(day: int) -> str:
    """次のレッスンのタイトルを取得"""
    next_lesson = get_lesson(day + 1)
    if next_lesson:
        return next_lesson["title"]
    return "卒業！"


# ---------------------------------------------------------------------------
# 台本生成（Claude API）
# ---------------------------------------------------------------------------
def generate_script(lesson: dict) -> tuple[str, str]:
    """レッスン情報から台本を生成する"""
    import anthropic

    client = anthropic.Anthropic()
    rules = RULES_PATH.read_text(encoding="utf-8")
    next_title = get_next_lesson_title(lesson["day"])

    topics_text = "\n".join(f"- {t}" for t in lesson["topics"])

    prompt = f"""あなたは株式投資教育のプロフェッショナルなラジオパーソナリティです。
以下のルールとレッスン情報をもとに、台本を作成してください。

## 台本生成ルール
{rules}

## 今日のレッスン情報
- **Day**: {lesson['day']} / 90
- **Phase**: {lesson['phase_num']} — {lesson['phase_title']}
- **タイトル**: {lesson['title']}
- **トピック**:
{topics_text}
- **キーメッセージ**: {lesson['key_message']}
- **次回予告**: Day {lesson['day'] + 1}「{next_title}」

## 重要な注意事項
- Day {lesson['day']}の内容として、上記トピックを深く掘り下げてください
- リスナーは積立投資を少しやっている初心者です
- 日常生活やビジネス一般に例えるとわかりやすい（特定業種の例えは不要）
- AIを業務で活用しているので、投資へのAI活用にも触れると良い
- 15分の尺に収まるよう、4500〜5000文字程度で

## 出力指示
以下の2つを出力してください:

### PART1: 台本（マークダウン形式）

### PART2: 読み上げテキスト
TTS用のプレーンテキスト:
- マークダウン記法は除去
- 英語の固有名詞はカタカナのみ（例: NISA → ニーサ、ETF → イーティーエフ、S&P500 → エスアンドピー500）
- 自然な話し言葉で句読点を入れる

必ず「===PART1===」と「===PART2===」で区切って出力してください。
"""

    print("  Claude APIで台本を生成中...")
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text

    if "===PART1===" in text and "===PART2===" in text:
        parts = text.split("===PART2===")
        script_md = parts[0].replace("===PART1===", "").strip()
        reading_text = parts[1].strip()
    else:
        script_md = text
        reading_text = text

    return script_md, reading_text


# ---------------------------------------------------------------------------
# 音声化（edge-tts）
# ---------------------------------------------------------------------------
async def generate_audio(text: str, output_path: Path):
    """edge-ttsでテキストを音声ファイル（MP3）に変換"""
    import edge_tts

    communicate = edge_tts.Communicate(text, TTS_VOICE, rate="+10%")
    await communicate.save(str(output_path))


# ---------------------------------------------------------------------------
# LINE送信
# ---------------------------------------------------------------------------
def send_line_audio(audio_url: str, duration_ms: int, lesson: dict):
    """LINE Messaging APIで音声メッセージを送信"""
    token = os.environ.get("LINE_CHANNEL_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not token or not user_id:
        print("  LINE設定なし — スキップ")
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    day = lesson["day"]
    title = lesson["title"]
    phase = lesson["phase_title"]

    body = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": f"📻 株式投資ラジオ Day {day}/90\n\n📖 {title}\n🎯 {phase}\n\n▶ 下の音声を再生してください",
            },
            {
                "type": "audio",
                "originalContentUrl": audio_url,
                "duration": duration_ms,
            },
        ],
    }

    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers,
        json=body,
    )

    if resp.status_code == 200:
        print("  LINE送信完了!")
    else:
        print(f"  LINE送信エラー: {resp.status_code} {resp.text}")
        # フォールバック：テキストのみ
        body["messages"] = [
            {
                "type": "text",
                "text": f"📻 株式投資ラジオ Day {day}/90\n\n📖 {title}\n🎯 {phase}\n\n🎧 音声: {audio_url}",
            }
        ]
        requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers,
            json=body,
        )


def send_line_text(message: str):
    """テキストメッセージのみ送信"""
    token = os.environ.get("LINE_CHANNEL_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    if not token or not user_id:
        return
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        json={"to": user_id, "messages": [{"type": "text", "text": message}]},
    )


def get_audio_duration_ms(file_path: Path) -> int:
    """MP3ファイルの長さをミリ秒で概算"""
    file_size = file_path.stat().st_size
    bitrate = 32000
    duration_sec = (file_size * 8) / bitrate
    return int(duration_sec * 1000)


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------
def main():
    day = get_current_day()
    print(f"=== 株式投資ラジオ Day {day}/90 ({TODAY_JP}) ===\n")

    if day > 90:
        print("カリキュラム完了！全90日のプログラムを終了しました。")
        send_line_text("🎓 株式投資ラジオ\n\n90日間のカリキュラムが完了しました！\nおめでとうございます！")
        return

    # ディレクトリ作成
    SCRIPT_OUTPUT_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)

    # APIキー確認
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("エラー: ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    # --- Step 1: レッスン情報取得 ---
    print(f"[1/3] レッスン情報を取得中...")
    lesson = get_lesson(day)
    if not lesson:
        print(f"Day {day} のレッスンが見つかりません")
        sys.exit(1)
    print(f"  タイトル: {lesson['title']}")
    print(f"  Phase: {lesson['phase_title']}")

    # --- Step 2: 台本生成 ---
    print(f"\n[2/3] 台本を生成中...")
    script_md, reading_text = generate_script(lesson)

    script_path = SCRIPT_OUTPUT_DIR / f"Day{day:02d}_{TODAY}_台本.md"
    script_path.write_text(script_md, encoding="utf-8")
    print(f"  台本保存: {script_path.name}")

    reading_path = SCRIPT_OUTPUT_DIR / f"Day{day:02d}_{TODAY}_読み上げ.txt"
    reading_path.write_text(reading_text, encoding="utf-8")
    print(f"  読み上げテキスト保存: {reading_path.name}")

    # --- Step 3: 音声生成 ---
    print(f"\n[3/3] 音声を生成中...")
    audio_path = AUDIO_DIR / f"Day{day:02d}_{TODAY}.mp3"
    asyncio.run(generate_audio(reading_text, audio_path))
    print(f"  音声ファイル保存: {audio_path.name}")

    # 進捗保存
    save_progress(day)

    # 完了
    duration_ms = get_audio_duration_ms(audio_path)
    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
    print(f"\n=== 完了 ===")
    print(f"  Day: {day}/90")
    print(f"  台本: {script_path}")
    print(f"  音声: {audio_path} ({file_size_mb:.1f} MB)")
    print(f"  尺: 約{duration_ms // 60000}分{(duration_ms % 60000) // 1000}秒")


if __name__ == "__main__":
    main()
