## 落點:`docs/` 是預設,被佔用才換

| 情況 | 落點 |
|---|---|
| `docs/` 不存在,或存在而空著 | **`docs/`**(預設不變) |
| `docs/` 已被佔用 | **`sdlc_docs/`** |

**佔用判準**(任一成立):

- 有 site generator 設定:`mkdocs.yml`、`docusaurus.config.*`、`_config.yml`、
  `conf.py`(Sphinx)、`book.toml`(mdBook),或 repo 設定把 `docs/` 當作 Pages source。
- 有生成產物標記:`docs/_build/`、`docs/.doctrees/`、`docs/site/`,或 `.gitignore` 忽略 `docs/` 的一部分。
- `docs/` 底下已有非我方內容,而其中沒有任何帳本。

**落點一律寫進 Guideline 表頭——宣告,不推論。** 下一棒不該再判一次;
判斷會隨環境變化,而宣告不會。

