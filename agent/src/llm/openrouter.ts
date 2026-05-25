import { openRouter as openRouterConfig } from "../config.js";

export async function openRouterChat(
  messages: { role: string; content: string }[],
  options?: { json?: boolean },
): Promise<string> {
  if (!openRouterConfig.apiKey) {
    throw new Error("OPENROUTER_API_KEY not set");
  }
  const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${openRouterConfig.apiKey}`,
      "Content-Type": "application/json",
      "HTTP-Referer": "https://github.com/EPIRjewelry/Blender_assist",
      "X-Title": "Blender Assist Agent",
    },
    body: JSON.stringify({
      model: openRouterConfig.model,
      messages,
      ...(options?.json ? { response_format: { type: "json_object" } } : {}),
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`OpenRouter ${res.status}: ${text}`);
  }
  const data = (await res.json()) as {
    id?: string;
    choices?: { message?: { content?: string } }[];
  };
  return data.choices?.[0]?.message?.content ?? "";
}

export function isOpenRouterEnabled(): boolean {
  return Boolean(openRouterConfig.apiKey);
}
