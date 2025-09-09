import os
import logging
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain.agents import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents.format_scratchpad.openai_tools import (
    format_to_openai_tool_messages,
)
from langchain.agents.output_parsers.openai_tools import OpenAIToolsAgentOutputParser
from langchain.agents import AgentExecutor
from pydantic import BaseModel, Field
from typing import List
from langchain_core.messages import HumanMessage, AIMessage

# Importar nossas funções lógicas
import logic_sizing

# --- CONFIGURAÇÃO INICIAL ---
load_dotenv()

# MELHORIA: Configurar logging para capturar erros detalhados
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Carregar os dados uma vez no início
print("Carregando dados de performance...")
df, df_alvo = logic_sizing.data_preparation('rperf_tabela.csv')
print("Dados carregados. O agente está pronto.")
print("="*50)

# --- DEFINIÇÃO DA ESTRUTURA DE DADOS DAS FERRAMENTAS ---
class Servidor(BaseModel):
    """Descreve um único tipo de servidor no inventário do cliente."""
    modelo: str = Field(description="O nome exato do modelo do servidor.")
    servidores: int = Field(description="A quantidade de servidores deste modelo.")
    cores: int = Field(description="O número de cores ativos por servidor.")
    utilizacao: float = Field(description="O pico de utilização a ser considerado para este servidor, em decimal (ex: 0.8 para 80%).")

class CalculoSizingInput(BaseModel):
    """Input para a ferramenta de cálculo de sizing."""
    inventario_cliente: List[Servidor] = Field(description="Uma lista de todos os servidores no ambiente atual do cliente.")
    taxa_anual_crescimento: float = Field(default=0.0, description="A taxa de crescimento anual em porcentagem (ex: 20 para 20%).")
    anos_projecao: int = Field(default=0, description="O número de anos para a projeção de crescimento.")

# --- CRIAÇÃO DA FERRAMENTA (TOOL) ---
@tool(args_schema=CalculoSizingInput)
def calcular_cenarios_de_sizing(inventario_cliente: List[Servidor], taxa_anual_crescimento: float, anos_projecao: int) -> str:
    """
    Use esta ferramenta APENAS quando tiver coletado TODAS as informações sobre os servidores
    atuais do cliente (modelo, quantidade, cores, utilização) e os requisitos de crescimento.
    Ela calcula e retorna os melhores cenários de consolidação para um novo hardware.
    """
    # Converter a lista de Pydantic models para o formato que nossa função espera (dicionário)
    inventario_dict = {
        s.modelo: {"servidores": s.servidores, "cores": s.cores, "utilizacao": s.utilizacao}
        for s in inventario_cliente
    }
    
    # --- MELHORIA 3: TRATAMENTO DE ERROS ---
    try:
        resultados = logic_sizing.calcular_e_ranquear_cenarios_completos(
            df=df,
            df_alvo=df_alvo,
            inventario_cliente=inventario_dict,
            taxa_anual_crescimento=taxa_anual_crescimento,
            anos_projecao=anos_projecao
        )

        if not resultados:
            return "Não foram encontrados cenários válidos com os dados fornecidos."

        # --- MELHORIA: FORMATAÇÃO COM MARKDOWN ---
        resposta_formatada = "Aqui estão os melhores cenários de sizing encontrados: 🏆\n"
        for i, c in enumerate(resultados):
            util_percent = c['utilizacao_cores'] * 100
            resposta_formatada += (
                f"\n**{i+1}. Modelo:** `{c['modelo_unico']}`\n"
                f"   - **Configuração:** {c['servidores']} servidor(es) com {c['cores_por_servidor']} cores ativos cada.\n"
                f"   - **Novo rPerf Total:** {c['rperf_novo']:.2f} (`+{c['excedente_rperf']:.2f}` de folga)\n"
                f"   - **Utilização de Cores:** {util_percent:.1f}%\n"
                "--------------------\n"
            )
        return resposta_formatada

    except Exception as e:
        # Loga o erro completo para debug interno
        logging.error(f"Erro ao executar a ferramenta de sizing: {e}", exc_info=True)
        # Retorna uma mensagem amigável para o usuário
        return "Ocorreu um erro interno ao processar sua solicitação. Verifique se os nomes dos modelos de servidor estão corretos e tente novamente."

# --- CRIAÇÃO DO AGENTE ---

# --- MELHORIA 5: CARREGAMENTO EXPLÍCITO DA API KEY ---
# Garante que a chave do .env seja usada corretamente
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("A variável de ambiente GROQ_API_KEY não foi encontrada...")

llm = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=api_key)

tools = [calcular_cenarios_de_sizing]
llm_with_tools = llm.bind_tools(tools)

# --- SYSTEM PROMPT MAIS ROBUSTO ---
# Mais diretivo para evitar loops e conversas fora de escopo
system_prompt = """Você é um assistente especialista em sizing de servidores IBM Power. Sua única função é ajudar os usuários a calcular cenários de consolidação de hardware.

Siga estas regras estritamente:
1.  Para saudações simples e conversas informais (como 'Olá', 'Oi', 'Tudo bem?'), responda de forma educada, se apresente brevemente e pergunte como pode ajudar com o sizing e explique como ele deve usa-lo guiando passo-a-passo. Não tente usar ferramentas para isso.
2.  Seu objetivo principal é coletar todas as informações para usar a ferramenta `calcular_cenarios_de_sizing`.
3.  As informações necessárias são: uma lista de servidores atuais (modelo, quantidade, cores, utilização) e, opcionalmente, uma projeção de crescimento (taxa e anos).
4.  Guie o usuário passo a passo. Peça uma informação de cada vez até ter tudo que precisa.
5.  NUNCA chame a ferramenta `calcular_cenarios_de_sizing` antes de ter pelo menos um servidor no inventário. Se o usuário pedir para calcular sem fornecer dados, explique que você precisa das informações primeiro.
6.  Não responda a perguntas que não sejam sobre sizing de servidores IBM Power. Se o usuário perguntar sobre outro assunto, gentilmente diga que você só pode ajudar com sizing.
7.  Não invente modelos de servidor ou qualquer outra informação.
"""


prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder(variable_name="chat_history"),
    ("user", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

agent = (
    {
        "input": lambda x: x["input"],
        "agent_scratchpad": lambda x: format_to_openai_tool_messages(x["intermediate_steps"]),
        "chat_history": lambda x: x["chat_history"],
    }
    | prompt
    | llm_with_tools
    | OpenAIToolsAgentOutputParser()
)

agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# --- MELHORIA 4: ORGANIZAÇÃO DO CÓDIGO EM FUNÇÕES ---
def run_chat():
    """Função principal que executa o loop de chat com o usuário."""
    # --- MELHORIA 2: GERENCIAMENTO DE HISTÓRICO MANUAL ---
    chat_history = []
    
    while True:
        user_input = input("Você: ")
        if user_input.lower() in ["exit", "sair"]:
            break
        
        # Adiciona a mensagem do usuário ao histórico
        chat_history.append(HumanMessage(content=user_input))
        
        result = agent_executor.invoke({
            "input": user_input,
            "chat_history": chat_history
        })
        
        # Adiciona a resposta do agente ao histórico
        chat_history.append(AIMessage(content=result["output"]))
        
        print("\nAgente:", result["output"])
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    run_chat()