# Bot Reversal+DSVWAP — Anàlisi de Cartera

Codi font del Treball Final de Grau **"Integració de criteris fonamentals i tècnics en la inversió: evidència empírica d'un model híbrid"**.

**Autor:** Esteve Mas Fàbrega
**Tutor:** Josep Purtí González
**Grau:** ADE — Universitat de Manresa, curs 2025-2026

## Descripció

Bot d'inversió que combina selecció fonamental d'actius amb un sistema tècnic automatitzat basat en la detecció de reversions del preu confirmades amb un nivell dinàmic Dynamic Swing VWAP. Aplicat sobre una cartera de 30 empreses seleccionades amb criteris fonamentals a partir del rànquing Forbes Global 2000 (2014), simulat durant el període 2015-2025.

## Característiques

- Sistema *long-only* amb retard d'una sessió (T+1) per evitar look-ahead bias
- Costos reals: comissió 0,25%, slippage 0,10%, manteniment B&H 0,15%
- Estimació fiscal IRPF (base de l'estalvi) amb regla dels dos mesos
- Comparació amb estratègia Buy & Hold i amb l'índex MSCI World
- Dashboard interactiu amb Streamlit

## Instal·lació local

```bash
git clone https://github.com/estevemasf/tfg-bot-inversio-hibrid.git
cd tfg-bot-inversio-hibrid
pip install -r requirements.txt
streamlit run bot_reversal_DSVWAP.py
```

## Llicència

MIT — ús, modificació i redistribució lliures amb finalitats acadèmiques o personals.

## Avís legal

Treball acadèmic. Els resultats no constitueixen recomanació d'inversió ni assessorament financer o fiscal.