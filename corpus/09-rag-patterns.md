# Agentic RAG 架構速查

這些名字聽起來各自獨立，其實是同一組模組的不同編排（Modular RAG 的主張）。

## 編排型態

| 型態 | 意思 |
|---|---|
| Linear | 固定順序跑完 |
| Conditional | 依判斷結果走不同分支 |
| Branching | 同時展開多路再合併 |
| Looping | 生成 → 批判 → 再檢索 |

## 各架構對照

| 架構 | 編排 | 關鍵動作 | 出處 |
|---|---|---|---|
| Naive RAG | Linear | 檢索一次就作答 | Lewis et al. 2020 |
| Rewrite-Retrieve-Read | Linear | 先改寫 query 再檢索 | Ma et al. 2023 |
| HyDE | Linear | 拿「猜的答案」而非問題去比對 | Gao et al. 2022 |
| RAG-Fusion | Branching | 多個 query 平行查再 RRF 融合 | Query Expansion 系列 |
| CRAG | Conditional | 評分後走 CORRECT / AMBIGUOUS / INCORRECT 三分支 | Yan et al. 2024 |
| Self-RAG | Looping | 每輪自問四個反思問題 | Asai et al. 2024 |
| Adaptive-RAG | Conditional | 先判斷複雜度再決定花多少力氣 | Jeong et al. 2024 |
| Modular RAG | 自適應 | 全部模組給 agent 自己編排 | Gao et al. 2024 |

## CRAG 的三分支

CRAG 的核心是檢索完先用一個輕量評估器打分，再依信心度選一條路：

| 動作 | 觸發條件 | 做什麼 |
|---|---|---|
| **Correct** | 高信心 | 把文件**精煉**成 knowledge strips：拆成小段 → 丟掉無關的 → 重組 |
| **Incorrect** | 低信心 | **丟掉**檢索結果，改用網路搜尋當替代知識來源 |
| **Ambiguous** | 判斷不了 | **兩者都用** —— 精煉後的內部知識 ＋ 網路結果，合併 |

兩個最常被講錯的地方：

**Correct 不是「直接拿去用」。** 論文的核心貢獻正是那個 decompose-then-recompose 精煉步驟 ——
就算整份文件相關，裡面仍有大量與問題無關的段落，不該同等對待。

**Ambiguous 不是「再查一輪」。** 它是「不確定時不賭單邊」，內部與外部知識同時採用。
改寫 query 是 Incorrect 分支去做網路搜尋時的動作。

關鍵是**評分要交給模型判斷，不能寫成 `if cosine < 0.5`** ——
「夠不夠回答這個問題」是語意判斷，cosine 0.8 可能完全沒用，0.4 可能正中紅心。
一旦寫成數值判斷，整套就退化回 pipeline RAG。

## Self-RAG 的四個反思問題

原論文是訓練模型輸出特殊 token，不訓練的話可以寫進 prompt 要它明講：

1. **要不要檢索？** 這題知識庫沒有就答不了嗎
2. **檢索到的相關嗎？** 逐塊評分
3. **我的草稿有被支撐嗎？** 逐句檢查，沒出處的刪掉
4. **這樣回答有用嗎？** 不夠完整就再補一輪

## 檢索層基礎

**RRF（Reciprocal Rank Fusion）** 融合多份排名，公式只有一行：

```
score(d) = Σ 1 / (60 + rank(d))
```

零參數。選它而不用加權相加，是因為 BM25 分數（0～40）和 cosine（0～1）
量綱不同，加權要調參而且會隨語料變。

**MMR（Maximal Marginal Relevance）** 在相關性和多樣性之間取平衡：

```
MMR = λ · 相關性 − (1−λ) · 跟已選片段的最大相似度
```

用來避免檢索結果都是同一段話的變體。

**中文一定要斷詞。** 中文沒有空白，不斷詞的話 BM25 拿到一整串字什麼都比不出來。
索引和查詢必須用同一套斷詞器。
