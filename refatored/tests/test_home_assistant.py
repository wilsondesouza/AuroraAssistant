import unittest
from refatored.home_assistant import (
    resolver_comando,
    DEVICE_REGISTRY,
    executar_comando_ha
)

class TestHomeAssistant(unittest.TestCase):

    def test_resolver_comando_valido(self):
        intencao = {
            "action": "turn_on",
            "target_name": "luz da sala",
            "parameters": {}
        }
        comando = resolver_comando(intencao)
        self.assertEqual(comando.get("domain"), "switch")
        self.assertEqual(comando.get("service"), "turn_on")
        self.assertEqual(comando.get("entity_id"), "switch.sala")
        self.assertEqual(comando.get("data"), {})

    def test_seguranca_entity_id_nao_pode_ser_sobrescrito(self):
        """
        CORREÇÃO CRÍTICA DE SEGURANÇA:
        Testa que 'parameters' vindo da LLM NÃO consegue sobrescrever o entity_id validado.
        """
        intencao_maliciosa = {
            "action": "turn_on",
            "target_name": "luz da sala",
            "parameters": {
                "entity_id": "switch.dispositivo_secreto_invasor",
                "injetar_comando": "rm -rf /"
            }
        }
        comando = resolver_comando(intencao_maliciosa)

        # O entity_id resolvido DEVE ser estritamente o do registry
        self.assertEqual(comando.get("entity_id"), "switch.sala")

        # Os parâmetros maliciosos devem ser ignorados pela whitelist
        self.assertNotIn("entity_id", comando.get("data", {}))
        self.assertNotIn("injetar_comando", comando.get("data", {}))

    def test_dispositivo_desconhecido(self):
        intencao = {
            "action": "turn_on",
            "target_name": "dispositivo inexistente",
            "parameters": {}
        }
        comando = resolver_comando(intencao)
        self.assertEqual(comando.get("error"), "unknown_device")

    def test_acao_nao_permitida(self):
        intencao = {
            "action": "trigger",
            "target_name": "luz da varanda",  # switch só aceita turn_on, turn_off, toggle
            "parameters": {}
        }
        comando = resolver_comando(intencao)
        self.assertEqual(comando.get("error"), "action_not_allowed")

    def test_ajuste_brilho_sanitizado(self):
        intencao = {
            "action": "set_brightness",
            "target_name": "luz da sala",
            "parameters": {"brightness_pct": 80}
        }
        comando = resolver_comando(intencao)
        self.assertEqual(comando.get("service"), "turn_on")
        self.assertEqual(comando.get("data", {}).get("brightness_pct"), 80)

    def test_ajuste_brilho_limites(self):
        # Valor acima de 100 deve ser limitado a 100
        intencao_alta = {
            "action": "set_brightness",
            "target_name": "luz da sala",
            "parameters": {"brightness_pct": 250}
        }
        comando_alto = resolver_comando(intencao_alta)
        self.assertEqual(comando_alto.get("data", {}).get("brightness_pct"), 100)

        # Valor abaixo de 0 deve ser limitado a 0
        intencao_baixa = {
            "action": "set_brightness",
            "target_name": "luz da sala",
            "parameters": {"brightness_pct": -20}
        }
        comando_baixo = resolver_comando(intencao_baixa)
        self.assertEqual(comando_baixo.get("data", {}).get("brightness_pct"), 0)

    def test_automacao_mapeada_para_trigger(self):
        intencao = {
            "action": "turn_on",
            "target_name": "youtube no quarto",
            "parameters": {}
        }
        comando = resolver_comando(intencao)
        self.assertEqual(comando.get("domain"), "automation")
        self.assertEqual(comando.get("service"), "trigger")
        self.assertEqual(comando.get("entity_id"), "automation.samsung_tv_youtube")


if __name__ == "__main__":
    unittest.main()

