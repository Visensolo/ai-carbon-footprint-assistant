"""
AI 碳足迹计算 + 行为优化助手 — Python 后端
功能：接收前端"其他"场景描述，调用 LLM 返回碳排量 + 优化建议

使用方式：
  1. pip install flask requests
  2. 设置环境变量：
     set LLM_API_KEY=your_key
     set LLM_API_URL=https://api.deepseek.com/v1/chat/completions（可选）
     set LLM_MODEL=deepseek-chat（可选）
  3. python app.py
  4. 浏览器打开 http://localhost:5000
"""

import os, json, re, requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder=".")

LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")


# ============================================================
#  LLM 提示词模板
# ============================================================
SYSTEM_PROMPT = """你是一位专业的碳排放计算专家和低碳生活顾问。你的任务有两部分：

## 任务1：计算碳排放量
根据用户描述的场景，使用权威碳排放系数（如IPCC、中国生态环境部数据）进行精准计算。

常用参考碳排系数（kg CO₂）：
【出行类】
- 步行：0.005 kg/km | 骑行：0.0033 kg/km | 公交：0.03 kg/km
- 地铁：0.03 kg/km | 私家车：0.15 kg/km | 高铁：0.008 kg/km
- 飞机：0.255 kg/km | 出租车：0.2 kg/km | 摩托车：0.1 kg/km
- 电动车：0.015 kg/km | 轮船：0.12 kg/km

【饮食类】（kg CO₂/kg 食材）
- 牛肉：27 | 羊肉：40 | 猪肉：14.8 | 鸡肉：6.9 | 鱼/海鲜：7
- 鸡蛋：5 | 牛奶：3 | 大米：2.7 | 面条：1.5 | 蔬菜：0.4
- 水果：0.3 | 豆腐：2 | 奶茶/饮料：0.5 kg/杯

## 任务2：生成个性化低碳建议
基于用户的具体场景，生成1-2条可落地的优化建议，每条标注预估可减排量。

## 输出格式
严格返回如下JSON，不要输出其他内容：
{"carbon": 数值(kg CO₂), "advice": "建议内容（含减排量）"}"""

EXAMPLES = [
    {
        "role": "user",
        "content": "场景类型：出行\n场景描述：高铁出行200公里"
    },
    {
        "role": "assistant",
        "content": '{"carbon": 1.6, "advice": "高铁200公里碳排1.6 kg，已是较低碳排的远途方式。若行程在500km以内，高铁替代飞机可减排约49 kg（飞机碳排约51 kg），减排率97%。"}'
    },
    {
        "role": "user",
        "content": "场景类型：饮食\n场景描述：每日牛肉150g"
    },
    {
        "role": "assistant",
        "content": '{"carbon": 4.05, "advice": "每日150g牛肉碳排4.05 kg，一周约28.4 kg。若将其中一半替换为鸡肉，每日可减排约1.6 kg（-39%），同时建议每周安排2天素食日。"}'
    },
    {
        "role": "user",
        "content": "场景类型：组合场景\n场景描述：地铁10公里 + 每日羊肉100g"
    },
    {
        "role": "assistant",
        "content": '{"carbon": 4.3, "advice": "地铁10公里仅碳排0.3 kg，非常低碳！羊肉100g碳排4 kg，在肉类中碳排较高。建议用鸡肉替代羊肉可减排约3.31 kg/100g（减排率83%），或每周减至2-3次羊肉。"}'
    }
]


def build_user_prompt(desc: str, category: str) -> str:
    cat_cn = {"travel": "出行", "diet": "饮食"}.get(category, "出行")
    return f"场景类型：{cat_cn}\n场景描述：{desc}"


def call_llm(desc: str, category: str) -> dict:
    """调用 LLM 接口，返回 {carbon, advice}"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(EXAMPLES)
    messages.append({"role": "user", "content": build_user_prompt(desc, category)})

    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 300,
    }
    resp = requests.post(LLM_API_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    # 解析 JSON
    match = re.search(r"\{[^}]+\}", content, re.DOTALL)
    if match:
        result = json.loads(match.group())
        return {
            "carbon": round(float(result.get("carbon", 0)), 2),
            "advice": result.get("advice", ""),
        }
    nums = re.findall(r"[\d.]+", content)
    if nums:
        return {"carbon": round(float(nums[0]), 2), "advice": ""}
    raise ValueError(f"无法解析 LLM 返回: {content}")


def fallback_calc(desc: str, category: str) -> dict:
    """本地模拟计算（无 API Key 时回退）"""
    text = desc.lower()
    nums = re.findall(r"[\d.]+", text)
    v = float(nums[0]) if nums else 10

    if category == "travel":
        factors = [
            (["高铁", "动车"], 0.008),
            (["飞机", "航班"], 0.255),
            (["摩托"], 0.1),
            (["电动"], 0.015),
            (["出租", "打车", "滴滴"], 0.2),
            (["船"], 0.12),
        ]
        for keys, f in factors:
            if any(k in text for k in keys):
                return {"carbon": round(v * f, 2), "advice": ""}
        return {"carbon": round(v * 0.15, 2), "advice": ""}
    else:
        factors = [
            (["牛肉", "牛排"], 0.027),
            (["羊肉"], 0.04),
            (["鱼", "海鲜"], 0.007),
            (["鸡蛋", "蛋"], 0.005),
            (["牛奶", "奶"], 0.003),
            (["奶茶", "饮料"], 0.05),
            (["米饭", "面"], 0.002),
            (["水果"], 0.003),
            (["豆腐"], 0.002),
        ]
        for keys, f in factors:
            if any(k in text for k in keys):
                return {"carbon": round(v * f, 2), "advice": ""}
        return {"carbon": round(v * 0.01, 2), "advice": ""}


# ============================================================
#  API 路由
# ============================================================
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/calc", methods=["POST"])
def api_calc():
    data = request.get_json()
    desc = data.get("desc", "")
    category = data.get("category", "travel")
    if not desc:
        return jsonify({"error": "描述不能为空"}), 400

    try:
        if LLM_API_KEY:
            result = call_llm(desc, category)
        else:
            result = fallback_calc(desc, category)
        return jsonify(result)
    except Exception as e:
        result = fallback_calc(desc, category)
        result["note"] = f"LLM 调用失败，使用本地估算: {e}"
        return jsonify(result)


if __name__ == "__main__":
    print("=" * 50)
    print("  AI 碳足迹计算助手 后端")
    print("  访问: http://localhost:5000")
    if not LLM_API_KEY:
        print("  ⚠ 未设置 LLM_API_KEY → 本地模拟模式")
    else:
        print(f"  ✓ LLM 模式: {LLM_MODEL}")
    print("=" * 50)
    app.run(debug=True, port=5000)
