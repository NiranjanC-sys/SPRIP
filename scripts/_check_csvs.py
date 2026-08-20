import pandas as pd

print("=== eligibility_table.csv ===")
df = pd.read_csv("DATA_EXTRACT/syn dt/data/gold/eligibility_table.csv")
print("Columns:", list(df.columns))
print("Shape:", df.shape)
print(df.head(3).to_string())
for c in df.columns:
    print(f"  {c}: nunique={df[c].nunique()}, sample={list(df[c].dropna().unique()[:5])}")

print("\n=== hcp_event_features.csv ===")
df2 = pd.read_csv("DATA_EXTRACT/syn dt/data/gold/hcp_event_features.csv")
print("Columns:", list(df2.columns))
print("Shape:", df2.shape)
print(df2.head(2).to_string())
for c in df2.columns:
    print(f"  {c}: nunique={df2[c].nunique()}, dtype={df2[c].dtype}, sample={list(df2[c].dropna().unique()[:4])}")

print("\n=== matched_pairs.csv ===")
df3 = pd.read_csv("DATA_EXTRACT/syn dt/data/gold/matched_pairs.csv")
print("Columns:", list(df3.columns))
print("Shape:", df3.shape)
print(df3.head(2).to_string())
for c in df3.columns:
    print(f"  {c}: nunique={df3[c].nunique()}, sample={list(df3[c].dropna().unique()[:4])}")
