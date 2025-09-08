# api.py (Corrected Version)

import pandas as pd
import math
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

# --- 1. Corrected Pydantic Models ---

class ClientMachine(BaseModel):
    # CHANGED: 'servidor' is now 'modelo' to match what Watson sends.
    modelo: str = Field(..., description="The base model of the server. Ex: S922")
    cores: int = Field(..., gt=0, description="Number of active cores per server.")
    quantidade: int = Field(default=1, gt=0, description="Quantity of servers with this configuration.")

class GrowthProjection(BaseModel):
    taxa_anual_percent: float = Field(default=0, ge=0, description="Annual percentage growth rate. Ex: 20")
    anos: int = Field(default=0, ge=0, description="Number of years for the projection.")

class SizingRequest(BaseModel):
    inventario_cliente: List[ClientMachine]
    projecao: Optional[GrowthProjection] = None

# --- FastAPI App Initialization ---
# Remember to replace this with your active ngrok URL
NGROK_URL = "https://98c8d465e351.ngrok-free.app" 

app = FastAPI(
    title="Sizing Automation API",
    description="An API to calculate and optimize Power server consolidation scenarios.",
    version="1.2.0", # Updated version
    servers=[{"url": NGROK_URL, "description": "Production Server via ngrok"}]
)

# --- Data Loading Logic (No changes here) ---
try:
    df = pd.read_csv('rperf_tabela.csv', delimiter=';')
    df['Cores_Maximos'] = pd.to_numeric(df['Cores_Maximos'].astype(str).str.replace('c', ''), errors='coerce')
    df.dropna(subset=['Cores_Maximos'], inplace=True)
    df['Cores_Maximos'] = df['Cores_Maximos'].astype(int)
    df['Frequencia_GHz'] = df['Frequencia_GHz'].astype(str)
    df['rPerf_por_Core'] = df['rPerf_Total'] / df['Cores_Maximos']
    df_alvo = df[df['Processador'].isin(['p10', 'p11'])].copy()
    print("✅ Performance data loaded and ready for API use.")
except Exception as e:
    print(f"❌ CRITICAL ERROR LOADING 'rperf_tabela.csv': {e}")
    df = pd.DataFrame()
    df_alvo = pd.DataFrame()

# --- API Endpoint ---
@app.post("/sizing/")
async def calcular_sizing(request: SizingRequest):
    if df.empty:
        raise HTTPException(status_code=500, detail="The performance database could not be loaded.")

    rperf_base = 0
    for machine in request.inventario_cliente:
        # CHANGED: Accessing 'machine.modelo' instead of 'machine.servidor'
        modelo_base = machine.modelo
        cores = machine.cores
        quantidade = machine.quantidade

        matches = df[
            df['Modelo_Base'].str.fullmatch(modelo_base, case=False) & 
            (df['Cores_Maximos'] == cores)
        ]
        
        if matches.empty:
            raise HTTPException(status_code=404, detail=f"No configuration found for server '{modelo_base}' with {cores} cores.")
        
        modelo_unico_encontrado = matches.index[0]
        
        rperf_total_modelo = quantidade * cores * df.loc[modelo_unico_encontrado, 'rPerf_por_Core']
        rperf_base += rperf_total_modelo

    # The rest of the calculation logic remains the same...
    rperf_final_requerido = rperf_base
    if request.projecao and request.projecao.anos > 0 and request.projecao.taxa_anual_percent > 0:
        taxa = request.projecao.taxa_anual_percent / 100
        rperf_final_requerido = rperf_base * (1 + taxa) ** request.projecao.anos

    cenarios_validos = []
    for modelo_alvo, dados_alvo in df_alvo.iterrows():
        modelo_base_alvo = dados_alvo['Modelo_Base']
        rperf_por_core_alvo = dados_alvo['rPerf_por_Core']
        cores_maximos_alvo = dados_alvo['Cores_Maximos']
        cores_necessarios = rperf_final_requerido / rperf_por_core_alvo
        num_servidores_real = math.ceil(cores_necessarios / cores_maximos_alvo)
        if num_servidores_real == 0: continue
        cores_por_servidor_media = cores_necessarios / num_servidores_real
        cores_ativos_arredondado = math.ceil(cores_por_servidor_media)
        cores_ativos_por_servidor = cores_ativos_arredondado + 1 if cores_ativos_arredondado % 2 != 0 else cores_ativos_arredondado
        utilizacao_cores = cores_ativos_por_servidor / cores_maximos_alvo
        if utilizacao_cores < 0.60 or cores_ativos_por_servidor > cores_maximos_alvo: continue
        rperf_novo_total = num_servidores_real * cores_ativos_por_servidor * rperf_por_core_alvo
        cenarios_validos.append({
            'modelo_unico': modelo_alvo, 'modelo_base': modelo_base_alvo,
            'servidores': num_servidores_real, 'cores_por_servidor': cores_ativos_por_servidor,
            'rperf_novo': round(rperf_novo_total, 2),
            'utilizacao_cores_percent': round(utilizacao_cores * 100, 2),
            'excedente_rperf': round(rperf_novo_total - rperf_final_requerido, 2)
        })

    melhores_por_modelo = {}
    for cenario in cenarios_validos:
        modelo_base = cenario['modelo_base']
        if modelo_base not in melhores_por_modelo or \
           cenario['servidores'] < melhores_por_modelo[modelo_base]['servidores'] or \
           (cenario['servidores'] == melhores_por_modelo[modelo_base]['servidores'] and \
            cenario['excedente_rperf'] < melhores_por_modelo[modelo_base]['excedente_rperf']):
            melhores_por_modelo[modelo_base] = cenario
            
    lista_de_campeoes = list(melhores_por_modelo.values())
    cenarios_finais_ordenados = sorted(lista_de_campeoes, key=lambda x: (x['servidores'], x['excedente_rperf']))
    
    return {
        "rperf_base_requerido": round(rperf_base, 2),
        "rperf_final_com_projecao": round(rperf_final_requerido, 2),
        "portfolio_recomendado": cenarios_finais_ordenados[:10]
    }