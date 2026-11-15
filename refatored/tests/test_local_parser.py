import unittest
from refatored.home_assistant import parse_home_assistant_local

class TestLocalParser(unittest.TestCase):

    def test_desligar_nao_interpreta_como_ligar(self):
        """Testa a correção do bug crítico onde 'desligar' virava 'turn_on'."""
        frases_desligar = [
            "desligar a luz da sala",
            "desliga a luz da sala",
            "desligar luz da sala",
            "apagar a luz da sala",
            "apaga a luz da sala",
            "desativa a luz da sala",
            "desligar a tv da sala",
        ]
        for frase in frases_desligar:
            with self.subTest(frase=frase):
                resultado = parse_home_assistant_local(frase)
                self.assertIsNotNone(resultado, f"Deveria ter reconhecido '{frase}'")
                self.assertEqual(
                    resultado.get("action"),
                    "turn_off",
                    f"Frase '{frase}' deveria ser 'turn_off', mas retornou '{resultado.get('action')}'"
                )

    def test_ligar_interpreta_como_turn_on(self):
        frases_ligar = [
            "ligar a luz da sala",
            "liga a luz da sala",
            "ligar luz da sala",
            "acender a luz da sala",
            "acende a luz da sala",
            "ativa a luz da sala",
            "ligar a tv do quarto",
        ]
        for frase in frases_ligar:
            with self.subTest(frase=frase):
                resultado = parse_home_assistant_local(frase)
                self.assertIsNotNone(resultado, f"Deveria ter reconhecido '{frase}'")
                self.assertEqual(
                    resultado.get("action"),
                    "turn_on",
                    f"Frase '{frase}' deveria ser 'turn_on'"
                )

    def test_rejeicao_de_frases_com_negacao(self):
        frases_negativas = [
            "não ligar a luz da sala",
            "não desliga a luz da sala",
            "não vai acender a luz da sala",
            "não apaga a tv da sala",
        ]
        for frase in frases_negativas:
            with self.subTest(frase=frase):
                resultado = parse_home_assistant_local(frase)
                self.assertIsNotNone(resultado)
                self.assertEqual(resultado.get("error"), "negation_detected")

    def test_prioridade_dispositivo_mais_especifico(self):
        """'luz do meu quarto' deve ter precedência sobre 'luz do quarto'."""
        cmd_meu_quarto = parse_home_assistant_local("acende a luz do meu quarto")
        self.assertIsNotNone(cmd_meu_quarto)
        self.assertEqual(cmd_meu_quarto.get("target_name"), "luz do meu quarto")

        cmd_quarto = parse_home_assistant_local("acende a luz do quarto")
        self.assertIsNotNone(cmd_quarto)
        self.assertEqual(cmd_quarto.get("target_name"), "luz do quarto")

    def test_automacao_ar_condicionado(self):
        cmd_ligar_ar = parse_home_assistant_local("ligar o ar condicionado")
        self.assertIsNotNone(cmd_ligar_ar)
        self.assertEqual(cmd_ligar_ar.get("action"), "trigger")
        self.assertEqual(cmd_ligar_ar.get("target_name"), "ligar ar condicionado")

        cmd_desligar_ar = parse_home_assistant_local("desligar o ar condicionado")
        self.assertIsNotNone(cmd_desligar_ar)
        self.assertEqual(cmd_desligar_ar.get("action"), "trigger")
        self.assertEqual(cmd_desligar_ar.get("target_name"), "desligar ar condicionado")

    def test_automacoes_de_tv(self):
        cmd_yt = parse_home_assistant_local("abrir youtube no quarto")
        self.assertIsNotNone(cmd_yt)
        self.assertEqual(cmd_yt.get("action"), "trigger")
        self.assertEqual(cmd_yt.get("target_name"), "youtube no quarto")

        cmd_stremio = parse_home_assistant_local("coloca stremio na sala")
        self.assertIsNotNone(cmd_stremio)
        self.assertEqual(cmd_stremio.get("action"), "trigger")
        self.assertEqual(cmd_stremio.get("target_name"), "stremio na sala")

    def test_dispositivo_desconhecido(self):
        cmd_desconhecido = parse_home_assistant_local("ligar o forno elétrico")
        self.assertIsNone(cmd_desconhecido)


if __name__ == "__main__":
    unittest.main()

