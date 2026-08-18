from mcp_drapp.html2text import to_text


def test_parrafos_y_entidades():
    assert to_text("<p>MC seguimiento hipotirodismo</p>") == "MC seguimiento hipotirodismo"
    assert to_text("<p>sue&ntilde;o&nbsp;malo</p>") == "sueño malo"


def test_br_es_salto_de_linea():
    assert to_text("<p>uno<br/>dos</p>") == "uno\ndos"


def test_lista():
    assert to_text("<ul><li>uno</li><li>dos</li></ul>") == "- uno\n- dos"


def test_tabla_con_saltos_de_linea_entre_celdas():
    """El HTML real trae \\n entre celdas: no deben romper la fila."""
    html = (
        "<table><thead>\n<tr>\n<th>Par&aacute;metro</th>\n<th>Resultado</th>\n</tr>\n"
        "</thead><tbody>\n<tr>\n<td><strong>Glucemia</strong></td>\n<td>88 mg/dL</td>\n"
        "</tr>\n</tbody></table>"
    )
    out = to_text(html)
    assert "| Parámetro | Resultado |" in out
    assert "| **Glucemia** | 88 mg/dL |" in out
    assert "|---|---|" in out


def test_pipe_en_celda_se_escapa():
    html = "<table><tr><td>a|b</td><td>c</td></tr></table>"
    assert r"a\|b" in to_text(html)


def test_vacio():
    assert to_text("") == ""
    assert to_text(None) == ""


def test_br_con_atributos_separa_igual():
    """El corpus real trae <br data-start=... /> pegado desde ChatGPT: 276 evoluciones."""
    assert to_text('<p>uno<br data-start="1" data-end="2" />dos</p>') == "uno\ndos"
    assert to_text("<p>uno<br>dos</p>") == "uno\ndos"
    assert to_text("<p>uno<br />dos</p>") == "uno\ndos"


def test_br_con_atributos_en_celda():
    out = to_text('<table><tr><td>a<br data-x="1" />b</td><td>c</td></tr></table>')
    assert "| a b | c |" in out
