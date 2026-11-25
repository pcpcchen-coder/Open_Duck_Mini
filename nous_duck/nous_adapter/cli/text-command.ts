import type { IntegrationToolId } from "../shared/aios-contracts.ts";

// ⚠️ 開發用的「文字命令 → 工具」對應。**不是 Nous、不是語音辨識、不是語言模型。**
// 用途：在 AIOS 還沒接上之前，用一句已經是文字的命令（duckctl say-command "往左看"）走一遍
// 「命令 → DuckAdapter → hub → duckd → 頭」，確認這條路是通的。
// 作法是固定的關鍵字規則：認得的句子很少，認不得就說認不得，不猜。
// 之後由 Nous 的模型決定呼叫哪個工具、帶什麼參數；這個檔案不搬進 AIOS。

export interface TextCommandMatch {
  tool: IntegrationToolId;
  args: Record<string, unknown>;
  /** 命中的規則（給人看，知道為什麼是這個工具）。 */
  rule: string;
}

export interface TextCommandContext {
  /** 鴨子回報的動作與表情清單（hello）；沒有連線時是空的。 */
  gestures: readonly string[];
  expressions: readonly string[];
}

/** 轉頭的幅度（rad）。0.2 rad ≈ 11.5°，在 duckd 服務預設的 ±15° 視窗內；「一點」減半。未經實機調整。 */
export const TEXT_COMMAND_ANGLE = 0.2;
const TURN_TIME_S = 1.5;

const has = (text: string, ...words: string[]) => words.some((w) => text.includes(w));

export function interpretTextCommand(input: string, context: TextCommandContext): TextCommandMatch | null {
  const text = input.trim().toLowerCase().replaceAll(/[\s，。！？!?,.]/g, "");
  if (!text) return null;
  const amount = has(text, "一點", "一下下", "alittle", "slightly") ? TEXT_COMMAND_ANGLE / 2 : TEXT_COMMAND_ANGLE;
  const look = (rule: string, args: Record<string, number>): TextCommandMatch => ({ tool: "app.duck.look", args: { ...args, duration_s: TURN_TIME_S }, rule });
  const gesture = (rule: string, name: string): TextCommandMatch | null => (context.gestures.includes(name) ? { tool: "app.duck.gesture", args: { name }, rule } : null);

  // 停止永遠最優先。
  if (has(text, "停", "不要動", "別動", "stop")) return { tool: "app.duck.stop", args: {}, rule: "停／不要動 → stop" };
  if (has(text, "狀態", "status", "你好嗎", "還好嗎")) return { tool: "app.duck.status", args: {}, rule: "狀態 → status" };

  // 預錄動作（只有鴨子回報清單裡有的才用）。
  if (has(text, "不要看我", "別看我", "不要跟", "stoptracking")) return { tool: "app.duck.track", args: { target: "none" }, rule: "不要看我 → track none" };
  if (has(text, "點頭", "點點頭", "nod")) return gesture("點頭 → gesture nod", "nod") ?? null;
  if (has(text, "搖頭", "搖搖頭", "shake")) return gesture("搖頭 → gesture shake", "shake") ?? null;
  if (has(text, "看看四周", "看四周", "四處看", "lookaround")) return gesture("看看四周 → gesture look_around", "look_around") ?? null;
  if (has(text, "歪頭", "tilt")) return gesture("歪頭 → gesture tilt", "tilt") ?? look("歪頭 → look head_roll", { head_roll: amount });

  // 轉頭（符號慣例照 duckd：head_yaw 正＝往左、head_pitch 正＝抬頭；方向尚未在實機確認）。
  if (has(text, "回正", "看前面", "看正面", "往前看", "lookforward", "center")) return look("回正 → look 全部 0", { neck_pitch: 0, head_pitch: 0, head_yaw: 0, head_roll: 0 });
  if (has(text, "左", "left")) return look("左 → look head_yaw +", { head_yaw: amount });
  if (has(text, "右", "right")) return look("右 → look head_yaw −", { head_yaw: -amount });
  if (has(text, "抬頭", "往上", "向上", "看上", "lookup")) return look("抬頭／往上 → look head_pitch +", { head_pitch: amount });
  if (has(text, "低頭", "往下", "向下", "看下", "lookdown")) return look("低頭／往下 → look head_pitch −", { head_pitch: -amount });

  // 表情（只有鴨子回報清單裡有的才用）。
  const moods: [string[], string][] = [
    [["開心", "笑", "高興", "happy", "smile"], "happy"],
    [["難過", "傷心", "sad"], "sad"],
    [["驚訝", "嚇", "surprised"], "surprised"],
    [["好奇", "curious"], "curious"],
    [["想睡", "睏", "sleepy"], "sleepy"],
    [["眨眼", "wink"], "wink"],
    [["平常", "正常表情", "neutral"], "neutral"],
  ];
  for (const [words, expression] of moods) {
    if (has(text, ...words) && context.expressions.includes(expression)) return { tool: "app.duck.express", args: { expression }, rule: `${words[0]} → express ${expression}` };
  }
  if (has(text, "看著我", "看我", "lookatme")) return { tool: "app.duck.track", args: { target: "face" }, rule: "看著我 → track face" };
  return null;
}

/** 認得的說法（給 help 與「認不得」時的提示）。 */
export const TEXT_COMMAND_EXAMPLES = ["往左看", "往右看一點", "抬頭", "低頭", "回正", "點頭", "搖頭", "歪頭", "看看四周", "笑一個", "看著我", "不要看我", "停", "狀態"] as const;
