import unittest
import json
from refatored.home_assistant import extrair_json, validar_esquema_intencao

class TestJsonExtractor(unittest.TestCase):

    def test_json_simples(self):
        texto = '{"action": "turn_on", "target_name": "luz da sala", "parameters": {}}'
        extraido = extrair_json(texto)
        self.assertIsNotNone(extraido)
        dados = json.loads(extraido)
        self.assertEqual(dados["action"], "turn_on")
        self.assertEqual(dados["target_name"], "luz da sala")
        self.assertEqual(dados["parameters"], {})

    def test_json_com_objetos_aninhados(self):
        """Testa o bug crítico do regex original que cortava no primeiro '}'."""
        texto = '{"action": "set_brightness", "target_name": "luz da sala", "parameters": {"brightness_pct": 50, "extra": {"nivel": 1}}}'
        extraido = extrair_json(texto)
        self.assertIsNotNone(extraido)
        dados = json.loads(extraido)
        self.assertEqual(dados["action"], "set_brightness")
        self.assertEqual(dados["parameters"]["brightness_pct"], 50)
        self.assertEqual(dados["parameters"]["extra"]["nivel"], 1)

    def test_json_em_bloco_markdown(self):
        texto = """Aqui está a intenção solicitada:
```json
{
  "action": "turn_off",
  "target_name": "tv da sala",
  "parameters": {}
}
```
Espero ter ajudado!"""
        extraido = extrair_json(texto)
        self.assertIsNotNone(extraido)
        dados = json.loads(extraido)
        self.assertEqual(dados["action"], "turn_off")
        self.assertEqual(dados["target_name"], "tv da sala")

    def test_json_malformado_sem_fechamento(self):
        texto = '{"action": "turn_on", "target_name": "luz da sala"'
        extraido = extrair_json(texto)
        self.assertIsNone(extraido)

    def test_validar_esquema_valido(self):
        valido, motivo = validar_esquema_intencao({
            "action": "turn_on",
            "target_name": "luz da sala",
            "parameters": {}
        })
        self.assertTrue(valido)
        self.assertIsNone(motivo)

    def test_validar_esquema_erro_esperado(self):
        valido, motivo = validar_esquema_intencao({"error": "unknown_device"})
        self.assertTrue(valido)
        self.assertIsNone(motivo)

    def test_validar_esquema_invalido(self):
        # Não é dicionário
        self.assertFalse(validar_esquema_intencao(["turn_on"])[0])
        # Falta target_name
        self.assertFalse(validar_esquema_intencao({"action": "turn_on"})[0])
        # Parameters não é dict
        self.assertFalse(validar_esquema_intencao({
            "action": "turn_on",
            "target_name": "luz",
            "parameters": "invalido"
        })[0])


if __name__ == "__main__":
    unittest.main()

