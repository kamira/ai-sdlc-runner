### 角色 → 載入 references(依職責載入子集)

啟動某角色時,先載**共同集**,再載該角色**基本集**,再依偵測情境追加:

**共同集(所有角色進場都載)**:`handshake` · `knowledge` · `doc-integrity`。

| 角色 | 基本載入(共同集之外) | 偵測到時追加 |
|------|----------------------|--------------|
| orchestrator | agent-hierarchy · agent-worklog · autonomy | 視情況全部 |
| analyst (A1) | requirement-analysis · structure-design | multi-repo→cross-repo;多分支→branch-isolation |
| lead-implementer (I1) | modification-guide · structure-design · agent-hierarchy · agent-worklog | multi-repo→cross-repo;有 CI→ci-cd;多分支→branch-isolation |
| sub-implementer (I1.x) | modification-guide · agent-worklog | — |
| verifier (V1) | acceptance-verification · independent-acceptance | 多分支→branch-isolation |
| integrator | independent-acceptance · cross-agent | — |
| 審議席(seat-*) | review-panel + 該席那一份領域 ref(risk/impact→modification-guide;drift→doc-integrity;compliance→knowledge;security→autonomy;consistency→branch-isolation·cross-repo) | —(唯讀、不可 spawn) |
| reviewer | independent-acceptance | — |

情境追加(偵測旗標):multi-repo→`cross-repo`、多分支→`branch-isolation`、並行/交接→`cross-agent`、自主連跑→`autonomy`、有 CI/CD→`ci-cd`。

> **程式可讀**:本表的機器版在 [`assets/role_refs.json`](../assets/role_refs.json)(**JSON 為程式的單一真相,本表是其人類視圖,兩者須一致**)。外部協調器可用 [`scripts/role_loadout.py`](../scripts/role_loadout.py) 查:`python3 scripts/role_loadout.py --role verifier`、`--role I1 --multi-repo --cicd`(印出該載清單;`--json` 給程式取用)。

