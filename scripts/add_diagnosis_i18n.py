#!/usr/bin/env python3
"""One-off: refresh the resume-diagnosis i18n tree in every locale JSON.

Rubric V4 checklist edition (October 2026): no score/band — per-item verdicts,
checklist counts, red-line result, a diagnosis target title
(求职意向) with a picker for multi-intention resumes, and the per-role
competency-model picker (Java P3–P8 level matrix; auto-match preselected,
manual confirm or explicit opt-out when nothing matches).

Run from apps/frontend:  uv run python ../../scripts/add_diagnosis_i18n.py
(or plain python3 — stdlib only).
"""

import json
from pathlib import Path

LOCALES: dict[str, dict[str, object]] = {
    "en": {
        "viewerButton": "Diagnose Resume",
        "title": "Resume Diagnosis",
        "subtitle": "Rubric V4 checklist: per-item verdicts plus a red-line result.",
        "loading": "Running the checklist — the AI review of semantic items can take a few minutes…",
        "error": "Diagnosis failed. Please try again.",
        "intro": "The report combines deterministic checks with one structured AI review. Optionally paste a target job description to also assess job-fit items.",
        "jdLabel": "Target job description (optional)",
        "jdPlaceholder": "Paste the job description here to enable job-fit checks…",
        "jdHint": "Without a job description, the 3 job-fit checks are marked N/A.",
        "run": "Start Diagnosis",
        "rerun": "Re-run",
        "specVersion": "Rubric {version}",
        "targetLabel": "Target role",
        "targetEmptyHint": "No job intention listed — the resume is diagnosed as a whole.",
        "targetChooseHint": "Several job intentions detected — pick the target role for this diagnosis:",
        "targetValue": "Target role: {title}",
        "competencyValue": "Competency model: {name}",
        "modelLabel": "Competency model",
        "modelLoading": "Loading competency models…",
        "modelLoadError": (
            "Could not load competency models — you can still run the base checklist."
        ),
        "modelMatchedHint": (
            "Auto-matched to the target role: {name}. Switch the level or run without a model."
        ),
        "modelNoMatchHint": (
            "No competency model matches the target role. Pick one to confirm, "
            "or run without a model."
        ),
        "modelNone": "Run without a competency model",
        "countsLabel": "Checklist result",
        "countsSummary": (
            "Applicable {effective} — conform {conform}, partial {partial}, "
            "nonconform {nonconform}; N/A {na}."
        ),
        "redlinePassed": "All red-line checks passed.",
        "redlineFailed": "Red-line checks failed — do not deliver this resume as-is:",
        "dimensionsTitle": "Results by dimension",
        "itemsTitle": "Checklist",
        "filterAll": "All",
        "filterProblems": "Problems",
        "allConform": "Every check conforms or is not applicable.",
        "rating": {"conform": "Conforms", "partial": "Partial", "nonconform": "Gap", "na": "N/A"},
        "redlineTag": "Red line",
        "method": {"objective": "Auto", "subjective": "AI"},
        "suggestionLabel": "Fix",
        "downloadWord": "Download Word",
        "downloadFailed": "Download failed. Please try again.",
        "fileStem": "resume-diagnosis-report",
    },
    "zh": {
        "viewerButton": "简历诊断",
        "title": "简历诊断",
        "subtitle": "按《简历诊断规范 V4》逐项给出符合 / 部分符合 / 不符合 / 不适用判定与红线结论。",
        "loading": "正在逐项检查——语义项由 AI 评审，可能需要几分钟……",
        "error": "诊断失败，请重试。",
        "intro": "报告结合确定性检查与一次结构化 AI 评审。可粘贴目标岗位描述，额外评估岗位匹配度检查项。",
        "jdLabel": "目标岗位描述（选填）",
        "jdPlaceholder": "粘贴岗位描述以启用岗位匹配度检查……",
        "jdHint": "未提供岗位描述时，3 项岗位匹配检查将标记为不适用。",
        "run": "开始诊断",
        "rerun": "重新诊断",
        "specVersion": "规范版本 {version}",
        "targetLabel": "诊断目标岗位",
        "targetEmptyHint": "未填写求职意向，将按简历整体内容进行诊断。",
        "targetChooseHint": "检测到多个求职意向，请选择本次诊断的目标岗位：",
        "targetValue": "诊断目标岗位：{title}",
        "competencyValue": "附加能力模型：{name}",
        "modelLabel": "岗位能力模型",
        "modelLoading": "正在加载岗位能力模型……",
        "modelLoadError": "能力模型加载失败，仍可按基础检查项进行诊断。",
        "modelMatchedHint": "已按目标岗位自动匹配：{name}。可切换职级或选择不使用模型。",
        "modelNoMatchHint": (
            "目标岗位未匹配到能力模型，可手动选择一个，或不使用模型直接检查。"
        ),
        "modelNone": "不使用能力模型",
        "countsLabel": "检查结果",
        "countsSummary": "适用 {effective} 项 —— 符合 {conform}、部分符合 {partial}、不符合 {nonconform}；不适用 {na} 项。",
        "redlinePassed": "红线检查全部通过。",
        "redlineFailed": "存在未通过的红线项，此简历不可直接投递：",
        "dimensionsTitle": "各维度检查结果",
        "itemsTitle": "检查明细",
        "filterAll": "全部",
        "filterProblems": "仅看问题",
        "allConform": "所有检查项均符合或不适用。",
        "rating": {"conform": "符合", "partial": "部分符合", "nonconform": "不符合", "na": "不适用"},
        "redlineTag": "红线",
        "method": {"objective": "自动", "subjective": "AI"},
        "suggestionLabel": "优化建议",
        "downloadWord": "下载 Word 文档",
        "downloadFailed": "下载失败，请重试。",
        "fileStem": "简历诊断报告",
    },
    "es": {
        "viewerButton": "Diagnosticar CV",
        "title": "Diagnóstico de CV",
        "subtitle": "Lista de comprobación de la rúbrica V4: veredictos por ítem y resultado de líneas rojas.",
        "loading": "Ejecutando la lista de comprobación; la revisión con IA de los ítems semánticos puede tardar unos minutos…",
        "error": "El diagnóstico falló. Inténtalo de nuevo.",
        "intro": "El informe combina comprobaciones deterministas con una revisión estructurada con IA. Pega opcionalmente la descripción del puesto objetivo para evaluar también la adecuación al empleo.",
        "jdLabel": "Descripción del puesto objetivo (opcional)",
        "jdPlaceholder": "Pega aquí la descripción del puesto para activar las comprobaciones de adecuación…",
        "jdHint": "Sin descripción del puesto, las 3 comprobaciones de adecuación se marcan como no aplicables.",
        "run": "Iniciar diagnóstico",
        "rerun": "Repetir",
        "specVersion": "Rúbrica {version}",
        "targetLabel": "Puesto objetivo",
        "targetEmptyHint": "No hay intención profesional indicada: el CV se diagnostica en su conjunto.",
        "targetChooseHint": "Se detectaron varias intenciones profesionales; elige el puesto objetivo de este diagnóstico:",
        "targetValue": "Puesto objetivo: {title}",
        "competencyValue": "Modelo de competencias: {name}",
        "modelLabel": "Modelo de competencias",
        "modelLoading": "Cargando modelos de competencias…",
        "modelLoadError": (
            "No se pudieron cargar los modelos de competencias; "
            "puedes ejecutar la lista de comprobación básica."
        ),
        "modelMatchedHint": (
            "Asignado automáticamente al puesto objetivo: {name}. "
            "Cambia de nivel o ejecuta sin modelo."
        ),
        "modelNoMatchHint": (
            "Ningún modelo de competencias coincide con el puesto objetivo. "
            "Elige uno para confirmar, o ejecuta sin modelo."
        ),
        "modelNone": "Ejecutar sin modelo de competencias",
        "countsLabel": "Resultado de la lista",
        "countsSummary": (
            "{effective} aplicables — conforme {conform}, parcial {partial}, "
            "no conforme {nonconform}; N/A {na}."
        ),
        "redlinePassed": "Todas las comprobaciones de línea roja han pasado.",
        "redlineFailed": "Hay líneas rojas no superadas; no envíes este CV tal cual:",
        "dimensionsTitle": "Resultados por dimensión",
        "itemsTitle": "Lista de comprobación",
        "filterAll": "Todo",
        "filterProblems": "Problemas",
        "allConform": "Todas las comprobaciones se cumplen o no aplican.",
        "rating": {"conform": "Conforme", "partial": "Parcial", "nonconform": "No conforme", "na": "N/A"},
        "redlineTag": "Línea roja",
        "method": {"objective": "Auto", "subjective": "IA"},
        "suggestionLabel": "Acción de mejora",
        "downloadWord": "Descargar documento Word",
        "downloadFailed": "Error al descargar. Inténtalo de nuevo.",
        "fileStem": "informe-diagnostico-cv",
    },
    "fr": {
        "viewerButton": "Diagnostiquer le CV",
        "title": "Diagnostic du CV",
        "subtitle": "Check-list de la barème V4 : verdict par critère et résultat des lignes rouges.",
        "loading": "Exécution de la check-list — l'analyse IA des éléments sémantiques peut prendre quelques minutes…",
        "error": "Échec du diagnostic. Veuillez réessayer.",
        "intro": "Le rapport combine des contrôles déterministes avec une revue IA structurée. Collez éventuellement la description du poste cible pour également évaluer l'adéquation au poste.",
        "jdLabel": "Description du poste cible (facultatif)",
        "jdPlaceholder": "Collez la description du poste pour activer les critères d'adéquation…",
        "jdHint": "Sans description de poste, les 3 critères d'adéquation sont marqués non applicables.",
        "run": "Lancer le diagnostic",
        "rerun": "Relancer",
        "specVersion": "Barème {version}",
        "targetLabel": "Poste visé",
        "targetEmptyHint": "Aucune intention professionnelle renseignée — le CV est diagnostiqué dans son ensemble.",
        "targetChooseHint": "Plusieurs intentions professionnelles détectées — choisissez le poste visé pour ce diagnostic :",
        "targetValue": "Poste visé : {title}",
        "competencyValue": "Modèle de compétences : {name}",
        "modelLabel": "Modèle de compétences",
        "modelLoading": "Chargement des modèles de compétences…",
        "modelLoadError": (
            "Impossible de charger les modèles de compétences ; "
            "vous pouvez quand même exécuter la check-list de base."
        ),
        "modelMatchedHint": (
            "Correspondance automatique avec le poste visé : {name}. "
            "Changez de niveau ou lancez sans modèle."
        ),
        "modelNoMatchHint": (
            "Aucun modèle de compétences ne correspond au poste visé. "
            "Choisissez-en un pour confirmer, ou lancez sans modèle."
        ),
        "modelNone": "Lancer sans modèle de compétences",
        "countsLabel": "Résultat de la check-list",
        "countsSummary": (
            "{effective} applicables — conforme {conform}, partiel {partial}, "
            "non conforme {nonconform} ; N/A {na}."
        ),
        "redlinePassed": "Tous les critères de ligne rouge sont réussis.",
        "redlineFailed": "Des lignes rouges ne sont pas validées — n'envoyez pas ce CV en l'état :",
        "dimensionsTitle": "Résultats par dimension",
        "itemsTitle": "Détail des critères",
        "filterAll": "Tout",
        "filterProblems": "Problèmes",
        "allConform": "Tous les critères sont conformes ou non applicables.",
        "rating": {"conform": "Conforme", "partial": "Partiel", "nonconform": "Non conforme", "na": "N/A"},
        "redlineTag": "Ligne rouge",
        "method": {"objective": "Auto", "subjective": "IA"},
        "suggestionLabel": "Action corrective",
        "downloadWord": "Télécharger le document Word",
        "downloadFailed": "Échec du téléchargement. Veuillez réessayer.",
        "fileStem": "rapport-diagnostic-cv",
    },
    "ja": {
        "viewerButton": "履歴書を診断",
        "title": "履歴書診断",
        "subtitle": "V4 ルーブリックのチェックリスト：項目ごとの判定とレッドライン結果。",
        "loading": "チェックリストを実行中——意味項目の AI レビューには数分かかる場合があります……",
        "error": "診断に失敗しました。もう一度お試しください。",
        "intro": "このレポートは決定論的チェックと 1 回の構造化 AI レビューを組み合わせます。任意で応募先の職務記述を貼り付けると、適合度項目も評価します。",
        "jdLabel": "応募先の職務記述（任意）",
        "jdPlaceholder": "職務記述を貼り付けて適合度チェックを有効化……",
        "jdHint": "職務記述がない場合、適合度 3 項目は非適用として扱われます。",
        "run": "診断を開始",
        "rerun": "再診断",
        "specVersion": "ルーブリック {version}",
        "targetLabel": "診断対象ポジション",
        "targetEmptyHint": "希望職種が未記入のため、履歴書全体を対象に診断します。",
        "targetChooseHint": "複数の希望職種が見つかりました。この診断の対象ポジションを選択してください：",
        "targetValue": "診断対象ポジション：{title}",
        "competencyValue": "コンピテンシーモデル：{name}",
        "modelLabel": "職務能力モデル",
        "modelLoading": "能力モデルを読み込み中……",
        "modelLoadError": "能力モデルを読み込めませんでした。基本チェックリストで診断できます。",
        "modelMatchedHint": (
            "対象ポジションに自動一致：{name}。レベルを変更するか、モデルなしで実行できます。"
        ),
        "modelNoMatchHint": (
            "対象ポジションに一致する能力モデルがありません。手動で選択するか、"
            "モデルなしで実行してください。"
        ),
        "modelNone": "能力モデルを使用しない",
        "countsLabel": "チェック結果",
        "countsSummary": (
            "適用 {effective} 項目 —— 適合 {conform}、部分的 {partial}、"
            "不適合 {nonconform}；非適用 {na}。"
        ),
        "redlinePassed": "すべてのレッドライン項目を通過しました。",
        "redlineFailed": "不合格のレッドラインがあります。このまま提出しないでください：",
        "dimensionsTitle": "軸別の結果",
        "itemsTitle": "チェック詳細",
        "filterAll": "すべて",
        "filterProblems": "問題のみ",
        "allConform": "すべての項目が適合または非適用です。",
        "rating": {"conform": "適合", "partial": "部分的", "nonconform": "不適合", "na": "非適用"},
        "redlineTag": "レッドライン",
        "method": {"objective": "自動", "subjective": "AI"},
        "suggestionLabel": "改善アクション",
        "downloadWord": "Word 文書をダウンロード",
        "downloadFailed": "ダウンロードに失敗しました。もう一度お試しください。",
        "fileStem": "履歴書診断レポート",
    },
    "ko": {
        "viewerButton": "이력서 진단",
        "title": "이력서 진단",
        "subtitle": "V4 루브릭 체크리스트: 항목별 판정과 레드라인 결과.",
        "loading": "체크리스트를 실행 중 — 의미 항목에 대한 AI 검토에 몇 분 정도 걸릴 수 있습니다…",
        "error": "진단에 실패했습니다. 다시 시도해 주세요.",
        "intro": "이 보고서는 결정론적 검사와 한 번의 구조화된 AI 검토를 결합합니다. 선택적으로 목표 직무 설명을 붙여넣으면 직무 적합도 항목도 평가합니다.",
        "jdLabel": "목표 직무 설명(선택)",
        "jdPlaceholder": "직무 설명을 붙여넣어 적합도 검사를 활성화하세요…",
        "jdHint": "직무 설명이 없으면 직무 적합도 3개 항목은 비해당으로 표시됩니다.",
        "run": "진단 시작",
        "rerun": "다시 진단",
        "specVersion": "루브릭 {version}",
        "targetLabel": "진단 대상 직무",
        "targetEmptyHint": "희망 직무가 비어 있어 이력서 전체를 대상으로 진단합니다.",
        "targetChooseHint": "여러 희망 직무가 감지되었습니다. 이번 진단의 대상 직무를 선택하세요:",
        "targetValue": "진단 대상 직무: {title}",
        "competencyValue": "역량 모델: {name}",
        "modelLabel": "직무 역량 모델",
        "modelLoading": "역량 모델을 불러오는 중…",
        "modelLoadError": "역량 모델을 불러오지 못했습니다. 기본 체크리스트로 진단할 수 있습니다.",
        "modelMatchedHint": (
            "대상 직무에 자동 매칭: {name}. 레벨을 변경하거나 모델 없이 실행할 수 있습니다."
        ),
        "modelNoMatchHint": (
            "대상 직무와 일치하는 역량 모델이 없습니다. 하나를 직접 선택하거나 "
            "모델 없이 실행하세요."
        ),
        "modelNone": "역량 모델 없이 실행",
        "countsLabel": "체크 결과",
        "countsSummary": (
            "적용 {effective}건 —— 적합 {conform}, 부분 적합 {partial}, "
            "부적합 {nonconform}; 비해당 {na}건."
        ),
        "redlinePassed": "모든 레드라인 항목을 통과했습니다.",
        "redlineFailed": "통과하지 못한 레드라인이 있습니다. 이 상태로 제출하지 마세요:",
        "dimensionsTitle": "차원별 결과",
        "itemsTitle": "검사 항목",
        "filterAll": "전체",
        "filterProblems": "문제만",
        "allConform": "모든 항목이 적합하거나 비해당입니다.",
        "rating": {"conform": "적합", "partial": "부분 적합", "nonconform": "부적합", "na": "비해당"},
        "redlineTag": "레드라인",
        "method": {"objective": "자동", "subjective": "AI"},
        "suggestionLabel": "개선 조치",
        "downloadWord": "Word 문서 다운로드",
        "downloadFailed": "다운로드에 실패했습니다. 다시 시도해 주세요.",
        "fileStem": "이력서-진단-리포트",
    },
    "pt-BR": {
        "viewerButton": "Diagnosticar currículo",
        "title": "Diagnóstico do currículo",
        "subtitle": "Checklist da rubrica V4: veredictos por item e resultado das linhas vermelhas.",
        "loading": "Executando o checklist — a análise da IA nos itens semânticos pode levar alguns minutos…",
        "error": "Falha no diagnóstico. Tente novamente.",
        "intro": "O relatório combina verificações determinísticas com uma revisão estruturada da IA. Cole opcionalmente a descrição da vaga-alvo para também avaliar os itens de aderência à vaga.",
        "jdLabel": "Descrição da vaga-alvo (opcional)",
        "jdPlaceholder": "Cole a descrição da vaga para ativar as verificações de aderência…",
        "jdHint": "Sem descrição de vaga, as 3 verificações de aderência são marcadas como não aplicáveis.",
        "run": "Iniciar diagnóstico",
        "rerun": "Repetir",
        "specVersion": "Rubrica {version}",
        "targetLabel": "Cargo-alvo",
        "targetEmptyHint": "Nenhum cargo de interesse informado — o currículo é diagnosticado como um todo.",
        "targetChooseHint": "Vários cargos de interesse detectados — escolha o cargo-alvo deste diagnóstico:",
        "targetValue": "Cargo-alvo: {title}",
        "competencyValue": "Modelo de competências: {name}",
        "modelLabel": "Modelo de competências",
        "modelLoading": "Carregando modelos de competências…",
        "modelLoadError": (
            "Não foi possível carregar os modelos de competências; "
            "você ainda pode executar o checklist básico."
        ),
        "modelMatchedHint": (
            "Correspondência automática com o cargo-alvo: {name}. "
            "Troque de nível ou execute sem modelo."
        ),
        "modelNoMatchHint": (
            "Nenhum modelo de competências corresponde ao cargo-alvo. "
            "Escolha um para confirmar ou execute sem modelo."
        ),
        "modelNone": "Executar sem modelo de competências",
        "countsLabel": "Resultado do checklist",
        "countsSummary": (
            "{effective} aplicáveis — em conformidade {conform}, parcial {partial}, "
            "em não conformidade {nonconform}; N/A {na}."
        ),
        "redlinePassed": "Todas as verificações de linha vermelha foram aprovadas.",
        "redlineFailed": "Há linhas vermelhas reprovadas — não envie este currículo no estado atual:",
        "dimensionsTitle": "Resultados por dimensão",
        "itemsTitle": "Lista de verificações",
        "filterAll": "Tudo",
        "filterProblems": "Problemas",
        "allConform": "Todos os itens estão em conformidade ou não se aplicam.",
        "rating": {"conform": "Conforme", "partial": "Parcial", "nonconform": "Não conforme", "na": "N/A"},
        "redlineTag": "Linha vermelha",
        "method": {"objective": "Auto", "subjective": "IA"},
        "suggestionLabel": "Ação de melhoria",
        "downloadWord": "Baixar documento Word",
        "downloadFailed": "Falha ao baixar. Tente novamente.",
        "fileStem": "relatorio-diagnostico-curriculo",
    },
}

# JSON keys used by the component, mapped to the translated string slots.
TREE: dict[str, str] = {
    "title": "title",
    "subtitle": "subtitle",
    "loading": "loading",
    "error": "error",
    "intro": "intro",
    "jobDescriptionLabel": "jdLabel",
    "jobDescriptionPlaceholder": "jdPlaceholder",
    "jdHint": "jdHint",
    "run": "run",
    "rerun": "rerun",
    "specVersion": "specVersion",
    "targetLabel": "targetLabel",
    "targetEmptyHint": "targetEmptyHint",
    "targetChooseHint": "targetChooseHint",
    "targetValue": "targetValue",
    "competencyValue": "competencyValue",
    "modelLabel": "modelLabel",
    "modelLoading": "modelLoading",
    "modelLoadError": "modelLoadError",
    "modelMatchedHint": "modelMatchedHint",
    "modelNoMatchHint": "modelNoMatchHint",
    "modelNone": "modelNone",
    "countsLabel": "countsLabel",
    "countsSummary": "countsSummary",
    "redlinePassed": "redlinePassed",
    "redlineFailed": "redlineFailed",
    "dimensionsTitle": "dimensionsTitle",
    "itemsTitle": "itemsTitle",
    "filterAll": "filterAll",
    "filterProblems": "filterProblems",
    "allConform": "allConform",
    "suggestionLabel": "suggestionLabel",
    "downloadWord": "downloadWord",
    "downloadFailed": "downloadFailed",
    "fileStem": "fileStem",
}

# Score-era keys removed in the checklist edition; drop them if stale data
# remains in a locale file.
REMOVED_KEYS = ("scoreLabel", "pointsDetail", "bandLabel")

messages_dir = Path(__file__).resolve().parents[1] / "apps" / "frontend" / "messages"

for locale, strings in LOCALES.items():
    path = messages_dir / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    data.setdefault("resumeViewer", {})["diagnoseResume"] = strings["viewerButton"]

    diagnosis = data.setdefault("diagnosis", {})
    for removed in REMOVED_KEYS:
        diagnosis.pop(removed, None)
    for json_key, slot in TREE.items():
        diagnosis[json_key] = strings[slot]
    diagnosis["rating"] = dict(strings["rating"])
    diagnosis["severity"] = {"redline": strings["redlineTag"]}
    diagnosis["method"] = dict(strings["method"])

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"updated {path.name}")

# Sanity: every locale got the exact same key structure as en.
en_data = json.loads((messages_dir / "en.json").read_text(encoding="utf-8"))


def shape(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: shape(v) for k, v in sorted(obj.items())}
    return type(obj).__name__


en_shape = shape(en_data.get("diagnosis"))
for locale in LOCALES:
    data = json.loads((messages_dir / f"{locale}.json").read_text(encoding="utf-8"))
    assert shape(data.get("diagnosis")) == en_shape, f"shape drift in {locale}"
    assert data["resumeViewer"]["diagnoseResume"]
print("parity OK across", len(LOCALES), "locales")
