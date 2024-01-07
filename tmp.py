import numpy as np

a =[None] * 4
a[1]=2
a[3]=44 

b = np.empty(10, dtype=np.float32).tolist()

c =[12,3,4,5] 
a.append(b)
print(b)
print(a)
print(isinstance(a, list))

