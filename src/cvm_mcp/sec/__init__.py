"""Fonte SEC/EDGAR: demonstrações financeiras de companhias listadas nos EUA,
a partir das APIs oficiais e gratuitas de dados XBRL da SEC
(`data.sec.gov`).

O desenho espelha o da CVM: a visão padrão é trimestral, o 4º trimestre é
derivado por diferença contra o exercício anual (10-K/20-F) e todo dado
derivado vem marcado. A diferença principal é que a SEC não tem um plano de
contas fixo — cada empresa escolhe as tags XBRL — então as contas passam por
um mapa de padronização (`mapping.py`) que registra qual tag foi usada.
"""
