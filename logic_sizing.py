import pandas as pd
import math

# --- PASSO 1: CARREGAR, PREPARAR E FILTRAR OS DADOS ---
def data_preparation(csv_path: str):
    """
    Carrega e prepara a tabela de performance a partir de um CSV.
    Retorna:
        df -> dataframe completo
        df_alvo -> dataframe filtrado apenas com P10 e P11
    """
    try:
        df = pd.read_csv(csv_path, delimiter=';')

        # Normaliza cores máximos
        df['Cores_Maximos'] = pd.to_numeric(
            df['Cores_Maximos'].astype(str).str.replace('c', ''), errors='coerce'
        )
        df.dropna(subset=['Cores_Maximos'], inplace=True)
        df['Cores_Maximos'] = df['Cores_Maximos'].astype(int)

        # Ajusta colunas
        df['Frequencia_GHz'] = df['Frequencia_GHz'].astype(str)
        df['rPerf_por_Core'] = df['rPerf_Total'] / df['Cores_Maximos']

        # Índice
        df = df.set_index('Modelo_Unico')

        print("✅ Tabela de performance carregada!")

        # Filtra apenas P10 e P11
        df_alvo = df[df['Processador'].isin(['p10', 'p11'])].copy()
        print(f"✅ Total de {len(df_alvo)} configurações P10 e P11 disponíveis para sizing.")
        print("-" * 50)

        return df, df_alvo

    except Exception as e:
        print(f"❌ ERRO ao processar o arquivo CSV: {e}")
        return None, None


# --- PASSO 2: COLETAR INFORMAÇÕES DO AMBIENTE ATUAL ---
def client_ambient(df):
    """
    Coleta as informações do ambiente atual do cliente via input().
    Retorna:
        inventario_client -> dicionário com dados dos servidores do cliente
    """
    inventario_client = {}
    print("\nDigite as informações do ambiente atual do cliente.")

    while True:
        busca_modelo = input("\nBusque pelo modelo da máquina (ou Enter para finalizar): ")
        if not busca_modelo:
            break

        matches = df.index[df.index.str.contains(busca_modelo, case=False)].tolist()
        modelo_selecionado = None

        if len(matches) == 0:
            print(f"⚠️ Nenhum modelo encontrado para '{busca_modelo}'.")
            continue
        elif len(matches) == 1:
            modelo_selecionado = matches[0]
            print(f"--> Modelo encontrado: {modelo_selecionado}")
        else:
            print("Múltiplas opções encontradas. Escolha uma:")
            for i, match in enumerate(matches):
                print(f"  [{i+1}] {match}")
            try:
                escolha = int(input("Digite o número da sua escolha: "))
                if 1 <= escolha <= len(matches):
                    modelo_selecionado = matches[escolha - 1]
                else:
                    print("⚠️ Escolha inválida.")
                    continue
            except ValueError:
                print("⚠️ Entrada inválida.")
                continue

        if modelo_selecionado:
            try:
                cores_por_servidor = int(input(f"Cores ativos POR SERVIDOR para '{modelo_selecionado}': "))

                cores_porc_input = input(
                    f"Qual o pico de utilização a ser considerado do servidor em % (padrão: 100): "
                )
                if cores_porc_input:
                    cores_porc_str = int(cores_porc_input)
                    cores_porc = cores_porc_str / 100
                else:
                    cores_porc_str = 100
                    cores_porc = 1.0

                num_servidores_str = input(f"Número de servidores com essa config. (padrão: 1): ")
                num_servidores = int(num_servidores_str) if num_servidores_str else 1

                if modelo_selecionado in inventario_client:
                    inventario_client[modelo_selecionado]['servidores'] += num_servidores
                else:
                    inventario_client[modelo_selecionado] = {
                        'cores': cores_por_servidor,
                        'servidores': num_servidores,
                        'utilizacao': cores_porc
                    }

                print(
                    f"✅ Adicionado: {num_servidores} servidor(es) com {cores_por_servidor} cores "
                    f"com um pico de {cores_porc_str}% do modelo {modelo_selecionado}."
                )
            except ValueError:
                print("⚠️ Entrada inválida.")
                continue

    if not inventario_client:
        print("Nenhuma máquina inserida.")
        return None

    return inventario_client


# --- PASSO 3: CALCULAR rPerf BASE E PROJEÇÃO DE CRESCIMENTO ---
def rperf_calc(df, inventario_client):
    """
    Calcula o rPerf atual e a projeção de crescimento.
    Retorna:
        rperf_final_requerido -> valor de rPerf necessário
    """
    rperf_base = 0
    print("\n--- Calculando rPerf Base do Ambiente Atual ---")

    for modelo, dados in inventario_client.items():
        rperf_total_modelo = (
            dados['servidores'] *
            dados['cores'] *
            df.loc[modelo, 'rPerf_por_Core'] *
            dados['utilizacao']
        )
        rperf_base += rperf_total_modelo
        utilizacao_percentual = dados['utilizacao'] * 100

        print(
            f"  - {dados['servidores']} servidor(es) x {dados['cores']} cores em {modelo} "
            f"x utilização {utilizacao_percentual:.0f}% = {rperf_total_modelo:.2f} rPerf"
        )

    print(f"\n=> rPerf Base Total Requerido (Hoje): {rperf_base:.2f}")

    rperf_final_requerido = rperf_base
    projecao = input("Deseja calcular uma projeção de crescimento? (s/n): ").lower()

    if projecao == 's':
        try:
            taxa_anual = float(input("Digite a taxa de crescimento anual em % (ex: 20): ")) / 100
            anos = int(input("Digite o número de anos para a projeção (ex: 3): "))
            rperf_final_requerido = rperf_base * (1 + taxa_anual) ** anos
            print(f"📈 Projeção: O rPerf requerido em {anos} anos será de {rperf_final_requerido:.2f}")
        except ValueError:
            print("⚠️ Entrada inválida para projeção. Usando o rPerf base.")

    print("=" * 50)
    return rperf_final_requerido


# --- PASSO 4: GERAR, FILTRAR E RANQUEAR CENÁRIOS ---
def rank_cenarios(df_alvo, rperf_final_requerido):
    """
    Gera cenários possíveis e retorna os melhores.
    Retorna:
        top_cenarios -> lista com os 10 melhores cenários
    """
    print("\n--- Gerando e Analisando Cenários de Consolidação ---")
    cenarios_validos = []

    for modelo_alvo, dados_alvo in df_alvo.iterrows():
        modelo_base_alvo = dados_alvo['Modelo_Base']
        rperf_por_core_alvo = dados_alvo['rPerf_por_Core']
        cores_maximos_alvo = dados_alvo['Cores_Maximos']

        cores_necessarios = rperf_final_requerido / rperf_por_core_alvo
        num_servidores_teorico = cores_necessarios / cores_maximos_alvo
        num_servidores_real = math.ceil(num_servidores_teorico)

        if num_servidores_real == 0:
            continue

        cores_por_servidor_media = cores_necessarios / num_servidores_real
        cores_ativos_arredondado = math.ceil(cores_por_servidor_media)
        cores_ativos_por_servidor = (
            cores_ativos_arredondado + 1
            if cores_ativos_arredondado % 2 != 0
            else cores_ativos_arredondado
        )

        utilizacao_cores = cores_ativos_por_servidor / cores_maximos_alvo

        if utilizacao_cores < 0.60 or cores_ativos_por_servidor > cores_maximos_alvo:
            continue

        rperf_novo_total = num_servidores_real * cores_ativos_por_servidor * rperf_por_core_alvo

        cenarios_validos.append({
            'modelo_unico': modelo_alvo,
            'modelo_base': modelo_base_alvo,
            'servidores': num_servidores_real,
            'cores_por_servidor': cores_ativos_por_servidor,
            'rperf_novo': rperf_novo_total,
            'utilizacao_cores': utilizacao_cores,
            'excedente_rperf': rperf_novo_total - rperf_final_requerido
        })

    # Seleciona o melhor de cada modelo base
    melhores_por_modelo = {}
    for cenario in cenarios_validos:
        modelo_base = cenario['modelo_base']
        if modelo_base not in melhores_por_modelo or \
           cenario['servidores'] < melhores_por_modelo[modelo_base]['servidores'] or \
           (cenario['servidores'] == melhores_por_modelo[modelo_base]['servidores'] and
            cenario['excedente_rperf'] < melhores_por_modelo[modelo_base]['excedente_rperf']):
            melhores_por_modelo[modelo_base] = cenario

    lista_de_campeoes = list(melhores_por_modelo.values())
    cenarios_finais_ordenados = sorted(
        lista_de_campeoes, key=lambda x: (x['servidores'], x['excedente_rperf'])
    )

    top_cenarios = cenarios_finais_ordenados[:10]

    print(f"{len(top_cenarios)} CENÁRIOS RECOMENDADOS (MELHOR OPÇÃO DE CADA MODELO) 🏆")
    for i, c in enumerate(top_cenarios):
        util_percent = c['utilizacao_cores'] * 100
        print(f"\n{i+1}. Modelo: {c['modelo_unico']}")
        print(f"   - ✅ Configuração: {c['servidores']} servidor(es) com {c['cores_por_servidor']} cores ativos cada.")
        print(f"   - 🚀 Novo rPerf Total: {c['rperf_novo']:.2f} (+{c['excedente_rperf']:.2f} de folga)")
        print(f"   - 📊 Utilização de Cores: {util_percent:.1f}%")
        print("-" * 20)

    return top_cenarios
