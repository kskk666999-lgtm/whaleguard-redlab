from __future__ import annotations

from copy import deepcopy
from typing import Any

LEARNING_PATH = [
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "I06",
    "I07",
    "I08",
    "I09",
    "I10",
    "I11",
    "I12",
    "A13",
    "A14",
    "A15",
    "A16",
    "A17",
]

MICRO_COURSES: dict[str, dict[str, Any]] = {
    "M01": {
        "id": "M01",
        "order": 1,
        "title": "HTTP 请求和响应是什么",
        "minutes": 3,
        "concepts": ["HTTP", "Request", "Response"],
        "plain_explanation": "浏览器先递交一张点菜单，服务器再把菜和回执一起送回来。",
        "analogy": "像在餐厅点餐：请求是菜单选择，响应是端上来的菜和小票。",
        "diagram": {"nodes": ["浏览器", "请求", "服务器", "响应"], "direction": "left_to_right"},
        "interactive_example": {
            "prompt": "哪一项更像 HTTP 响应？",
            "choices": ["GET /lessons", "200 OK + 课程内容", "浏览器地址栏"],
            "answer_index": 1,
            "explanation": "状态码和返回内容由服务器响应给浏览器。",
        },
    },
    "M02": {
        "id": "M02",
        "order": 2,
        "title": "LLM 应用为什么不只是聊天框",
        "minutes": 4,
        "concepts": ["LLM", "Application"],
        "plain_explanation": "LLM 负责理解和生成文字，应用还会连接数据、权限和工具。",
        "analogy": "LLM 像大脑，应用还需要眼睛、记事本、门禁和双手。",
        "diagram": {"nodes": ["用户", "LLM", "数据/工具", "结果"], "direction": "left_to_right"},
        "interactive_example": {
            "prompt": "哪一步最需要独立权限检查？",
            "choices": ["模型组织一句话", "工具读取工资记录", "用户输入问候"],
            "answer_index": 1,
            "explanation": "模型想调用工具不等于用户真的有权限。",
        },
    },
    "M03": {
        "id": "M03",
        "order": 3,
        "title": "System Prompt 是什么",
        "minutes": 3,
        "concepts": ["Prompt", "System Prompt"],
        "plain_explanation": "它是应用交给模型的内部工作说明，不应该被普通输入随意改写。",
        "analogy": "像员工手册：顾客可以提需求，但不能自己改公司的工作规则。",
        "diagram": {"nodes": ["系统规则", "用户输入", "模型决定"], "direction": "top_to_bottom"},
        "interactive_example": {
            "prompt": "用户说“忽略所有规则”时应该怎样？",
            "choices": ["照做", "仍按可信规则处理", "打印内部规则"],
            "answer_index": 1,
            "explanation": "不可信输入不能覆盖更高优先级的可信规则。",
        },
    },
    "M04": {
        "id": "M04",
        "order": 4,
        "title": "RAG 是什么",
        "minutes": 4,
        "concepts": ["RAG", "Context"],
        "plain_explanation": "RAG 会先查资料，再把找到的片段交给模型回答。",
        "analogy": "像开卷考试：先翻资料，但资料里的批注也可能不可信。",
        "diagram": {"nodes": ["问题", "检索", "资料片段", "LLM"], "direction": "left_to_right"},
        "interactive_example": {
            "prompt": "检索到的网页内容应该被当成什么？",
            "choices": ["绝对可信规则", "不可信数据", "管理员命令"],
            "answer_index": 1,
            "explanation": "外部资料可以提供事实，但不能自动获得指令权限。",
        },
    },
    "M05": {
        "id": "M05",
        "order": 5,
        "title": "Vector 和 Embedding 是什么",
        "minutes": 4,
        "concepts": ["Vector", "Embedding"],
        "plain_explanation": "Embedding 把文字变成数字坐标，Vector 检索用距离寻找相似内容。",
        "analogy": "像给每段文字放到地图上，意思越接近，地图位置通常越近。",
        "diagram": {
            "nodes": ["文字", "数字坐标", "相似度", "检索结果"],
            "direction": "left_to_right",
        },
        "interactive_example": {
            "prompt": "相似度高就一定安全可靠吗？",
            "choices": ["一定", "不一定", "只要很短就一定"],
            "answer_index": 1,
            "explanation": "相似只代表内容接近，不代表来源可信或授权正确。",
        },
    },
    "M06": {
        "id": "M06",
        "order": 6,
        "title": "Tool 是什么",
        "minutes": 3,
        "concepts": ["Tool", "Permission"],
        "plain_explanation": "Tool 是应用允许 AI 请求执行的具体能力，例如查天气或读文档。",
        "analogy": "像工具箱里的钥匙：每把钥匙只能开被授权的门。",
        "diagram": {
            "nodes": ["模型建议", "权限检查", "工具", "结果"],
            "direction": "left_to_right",
        },
        "interactive_example": {
            "prompt": "模型要求读工资表时谁做最终决定？",
            "choices": ["模型自己", "权限策略", "随机决定"],
            "answer_index": 1,
            "explanation": "工具层必须独立验证身份、权限和审批。",
        },
    },
    "M07": {
        "id": "M07",
        "order": 7,
        "title": "Agent 是什么",
        "minutes": 4,
        "concepts": ["Agent", "Goal"],
        "plain_explanation": "Agent 会为了目标规划多步动作，并可能使用记忆和工具。",
        "analogy": "像能自己安排步骤的助理，但每一步仍要受门禁和预算约束。",
        "diagram": {"nodes": ["目标", "计划", "动作", "观察", "下一步"], "direction": "cycle"},
        "interactive_example": {
            "prompt": "Agent 最危险的误区是什么？",
            "choices": ["回复太短", "目标正确就允许任意动作", "使用中文"],
            "answer_index": 1,
            "explanation": "目标和每个动作都需要独立的安全边界。",
        },
    },
    "M08": {
        "id": "M08",
        "order": 8,
        "title": "MCP 是什么",
        "minutes": 4,
        "concepts": ["MCP", "Tool Metadata"],
        "plain_explanation": "MCP 让 AI 应用用统一方式发现和调用外部工具与资源。",
        "analogy": "像统一规格的插座，但插上去的设备仍要检查来源和权限。",
        "diagram": {
            "nodes": ["AI 应用", "MCP Server", "Tool", "资源"],
            "direction": "left_to_right",
        },
        "interactive_example": {
            "prompt": "Tool 描述写得很友好就可以信任吗？",
            "choices": ["可以", "不可以，仍需验证来源", "名字短就可以"],
            "answer_index": 1,
            "explanation": "名称和描述也是不可信供应链输入。",
        },
    },
    "M09": {
        "id": "M09",
        "order": 9,
        "title": "Prompt Injection 是什么",
        "minutes": 4,
        "concepts": ["Prompt Injection", "Trust Boundary"],
        "plain_explanation": "攻击者把数据伪装成指令，诱导模型改变原本目标或泄露内容。",
        "analogy": "像在送货单里夹一张假老板命令，员工没有核验就照做。",
        "diagram": {
            "nodes": ["不可信内容", "伪装指令", "模型", "危险动作"],
            "direction": "left_to_right",
        },
        "interactive_example": {
            "prompt": "最重要的防线是什么？",
            "choices": ["只禁一个关键词", "分离数据与指令并限制动作", "让提示词更长"],
            "answer_index": 1,
            "explanation": "单一关键词容易绕过，权限和数据边界必须真正执行。",
        },
    },
    "M10": {
        "id": "M10",
        "order": 10,
        "title": "权限和授权范围是什么",
        "minutes": 5,
        "concepts": ["Authorization", "Scope"],
        "plain_explanation": "权限回答“能做什么”，Scope 回答“可以对哪些明确目标做”。",
        "analogy": "像门禁卡：既限定能开的门，也限定有效时间和操作类型。",
        "diagram": {
            "nodes": ["身份", "权限", "Scope", "审批", "动作"],
            "direction": "left_to_right",
        },
        "interactive_example": {
            "prompt": "获准测试 A 网站后可以顺便测试相似域名 B 吗？",
            "choices": ["可以", "不可以，必须另行明确授权", "只读就可以"],
            "answer_index": 1,
            "explanation": "安全测试必须始终停留在精确授权范围内。",
        },
    },
}

SCENARIO_LEARNING: dict[str, dict[str, Any]] = {
    "B01": {
        "skills": ["prompt_injection", "agent_security", "output_validation"],
        "layer": ["Prompt", "LLM", "Output"],
        "prerequisites": [],
        "goal": "看懂不可信输入如何改变 Agent 目标并触发泄露。",
        "why_it_matters": "真实应用会同时接收可信规则和不可信用户内容。",
        "real_world_example": "客服机器人被用户诱导忽略内部规则。",
    },
    "B02": {
        "skills": ["sensitive_data", "output_validation"],
        "layer": ["Context", "LLM", "Output"],
        "prerequisites": ["B01"],
        "goal": "识别隐藏上下文泄露并追踪数据来源。",
        "why_it_matters": "System Prompt、开发者上下文和调试信息可能包含敏感内容。",
        "real_world_example": "助手把仅供内部使用的说明原样返回给用户。",
    },
    "B03": {
        "skills": ["prompt_injection", "rag_security", "sensitive_data"],
        "layer": ["RAG", "Context", "Agent"],
        "prerequisites": ["B01"],
        "goal": "看懂外部文档中的伪指令如何污染 RAG 决策。",
        "why_it_matters": "检索内容来自外部，不能自动获得系统指令的信任级别。",
        "real_world_example": "知识库文档夹带指令，诱导助手读取内部数据。",
    },
    "B04": {
        "skills": ["tool_security", "agent_security", "authorization", "scope"],
        "layer": ["Planner", "Tool", "Policy"],
        "prerequisites": ["B01"],
        "goal": "区分模型意图与真正的工具授权。",
        "why_it_matters": "模型想做某事不等于当前用户被允许做。",
        "real_world_example": "普通员工的助手未经审批读取工资工具。",
    },
    "B05": {
        "skills": ["mcp_security", "tool_security", "prompt_injection"],
        "layer": ["MCP", "Metadata", "Planner"],
        "prerequisites": ["B04"],
        "goal": "把 MCP Tool 描述当作不可信供应链输入。",
        "why_it_matters": "工具元数据也可能包含操纵模型的文字。",
        "real_world_example": "恶意 Tool 用描述投毒赢得 Agent 选择。",
    },
    "I06": {
        "skills": ["rag_security", "sensitive_data", "authorization"],
        "layer": ["RAG", "Data", "Policy"],
        "prerequisites": ["B03"],
        "goal": "验证多租户 RAG 的数据隔离。",
        "why_it_matters": "相似度检索不能代替租户 ACL。",
        "real_world_example": "用户检索到另一租户的工资记录。",
    },
    "I07": {
        "skills": ["rag_security"],
        "layer": ["Embedding", "Vector", "RAG"],
        "prerequisites": ["B03"],
        "goal": "理解相似度检索中的向量投毒。",
        "why_it_matters": "高相似度不代表内容可信。",
        "real_world_example": "污染片段抢占正常检索结果。",
    },
    "I08": {
        "skills": ["tool_security", "output_validation"],
        "layer": ["LLM", "Schema", "Tool"],
        "prerequisites": ["B04"],
        "goal": "验证工具参数而不是直接执行模型输出。",
        "why_it_matters": "结构化参数仍可能越权或越界。",
        "real_world_example": "模型生成越出允许目录的文件参数。",
    },
    "I09": {
        "skills": ["agent_security", "rag_security"],
        "layer": ["Memory", "Context", "Agent"],
        "prerequisites": ["B03"],
        "goal": "识别跨会话生效的恶意记忆。",
        "why_it_matters": "持久记忆会把一次污染带到未来任务。",
        "real_world_example": "Agent 保存了未经验证的长期指令。",
    },
    "I10": {
        "skills": ["authorization", "scope", "sensitive_data"],
        "layer": ["Identity", "Object", "Tool"],
        "prerequisites": ["B04"],
        "goal": "识别 Agent 工具中的对象级授权缺失。",
        "why_it_matters": "只验证已登录并不足以证明能访问目标对象。",
        "real_world_example": "Agent 修改参数后读取另一个用户的记录。",
    },
    "I11": {
        "skills": ["output_validation", "sensitive_data", "prompt_injection"],
        "layer": ["LLM", "Renderer", "Browser"],
        "prerequisites": ["B01"],
        "goal": "安全处理模型生成的富文本和主动内容。",
        "why_it_matters": "模型输出仍是不可信数据。",
        "real_world_example": "Markdown 渲染器执行模型生成的活动内容。",
    },
    "I12": {
        "skills": ["agent_security", "tool_security"],
        "layer": ["Agent", "Resource", "Policy"],
        "prerequisites": ["B04"],
        "goal": "为 Agent 循环设置预算、速率和熔断。",
        "why_it_matters": "自主循环可能放大成本并引发级联故障。",
        "real_world_example": "Agent 重复调用工具直到耗尽预算。",
    },
    "A13": {
        "skills": ["agent_security", "authorization"],
        "layer": ["Agent", "A2A", "Identity"],
        "prerequisites": ["I09", "I10"],
        "goal": "验证 Agent 间消息的身份与来源。",
        "why_it_matters": "多 Agent 系统会放大伪造身份的影响。",
        "real_world_example": "陌生 Agent 冒充受信队友发送命令。",
    },
    "A14": {
        "skills": ["mcp_security", "tool_security"],
        "layer": ["Supply Chain", "Manifest", "Agent"],
        "prerequisites": ["B05", "I08"],
        "goal": "验证插件清单、来源和完整性。",
        "why_it_matters": "Agent 会把供应链组件当成自己的执行能力。",
        "real_world_example": "被篡改的插件清单引入未批准能力。",
    },
    "A15": {
        "skills": ["agent_security", "rag_security"],
        "layer": ["Multi-Agent", "Data", "Decision"],
        "prerequisites": ["A13", "I07"],
        "goal": "阻止错误信息在多 Agent 之间级联。",
        "why_it_matters": "一个错误结论可能被后续 Agent 当成已验证事实。",
        "real_world_example": "污染信息沿任务链传播并触发错误动作。",
    },
    "A16": {
        "skills": ["mcp_security", "authorization", "scope"],
        "layer": ["MCP", "OAuth", "Identity"],
        "prerequisites": ["B05", "I10"],
        "goal": "验证 MCP 身份令牌的签发者和受众。",
        "why_it_matters": "令牌存在不代表它由正确系统签发给正确服务。",
        "real_world_example": "错误签发者的令牌被混淆为有效身份。",
    },
    "A17": {
        "skills": ["agent_security", "authorization"],
        "layer": ["Agent", "Human", "Approval"],
        "prerequisites": ["A13", "A16"],
        "goal": "识别 Rogue Agent 对人工审批的操纵。",
        "why_it_matters": "人工在环只有获得独立证据时才是有效控制。",
        "real_world_example": "Agent 用自己生成的理由诱导审批高风险动作。",
    },
}

SKILLS: dict[str, dict[str, Any]] = {
    "prompt_injection": {"name": "Prompt Injection", "description": "区分可信指令与不可信内容。"},
    "sensitive_data": {"name": "Sensitive Data", "description": "识别并阻止敏感数据跨越边界。"},
    "rag_security": {"name": "RAG Security", "description": "验证检索来源、隔离和向量完整性。"},
    "tool_security": {"name": "Tool Security", "description": "约束工具选择、参数和执行权限。"},
    "agent_security": {"name": "Agent Security", "description": "保护目标、记忆和多步行动。"},
    "mcp_security": {"name": "MCP Security", "description": "评估 MCP 元数据、身份和供应链。"},
    "authorization": {"name": "Authorization", "description": "验证身份、对象权限与审批。"},
    "scope": {"name": "Scope", "description": "让动作始终停留在明确授权范围内。"},
    "output_validation": {
        "name": "Output Validation",
        "description": "把模型输出作为不可信数据处理。",
    },
    "evidence_analysis": {
        "name": "Evidence Analysis",
        "description": "用事件证据证明来源、决策和结果。",
    },
}


def list_micro_courses() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in MICRO_COURSES.values()]


def get_micro_course(course_id: str) -> dict[str, Any]:
    try:
        return deepcopy(MICRO_COURSES[course_id.upper()])
    except KeyError as exc:
        raise KeyError(f"Unknown Academy micro-course: {course_id}") from exc


def get_scenario_learning(scenario_id: str) -> dict[str, Any]:
    try:
        return deepcopy(SCENARIO_LEARNING[scenario_id.upper()])
    except KeyError as exc:
        raise KeyError(f"Unknown Academy learning metadata: {scenario_id}") from exc


def scenarios_for_skill(skill_id: str) -> list[str]:
    if skill_id == "evidence_analysis":
        return list(LEARNING_PATH)
    return [
        scenario_id
        for scenario_id in LEARNING_PATH
        if skill_id in SCENARIO_LEARNING[scenario_id]["skills"]
    ]
