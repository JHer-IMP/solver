import pandas as pd

# 查看距离文件的实际列名
df = pd.read_csv("destination_with_distance.csv")
print("列名:", list(df.columns))
print("\n前3行数据:")
print(df.head(3))
print("\n数据类型:")
print(df.dtypes)