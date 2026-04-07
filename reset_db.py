import os

if os.path.exists("final_pro.db"):
    os.remove("final_pro.db")
    print("DB apagada")
else:
    print("DB não existe")
