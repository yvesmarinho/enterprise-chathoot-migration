# Relatório de Validação S3 Attachments

**Timestamp**: 2026-05-14T09:33:24.977201
**Instância**: `chat-vya-digital`
**Account**: Unimed Guaxupé (ID: 25)

---

## 📊 Estatísticas Gerais

| Métrica | Valor |
|---------|-------|
| Total attachments na account | 1930 |
| Total com blob S3 válido | 1919 |
| Range de datas | 2026-01-01 → 2026-05-13 |
| Limite aplicado | 100 |
| Offset | 0 |

---

## ✅ Resultados da Validação

| Métrica | Valor |
|---------|-------|
| **Total validado** | **100** |
| ✅ Sucesso (HTTP 200) | 97 |
| ❌ Falhas | 3 |
| **Taxa de sucesso** | **97.0%** |

---
## ❌ Attachments com Falha (3)

| Attachment ID | Filename | Content Type | Error | Blob Key |
|--------------|----------|--------------|-------|----------|
| 64117 | File.jpg | image/jpeg | HTTP 404 | `0zuxwjzm43rkkk0z4jbt6w70f4r6...` |
| 64116 | File.jpg | image/jpeg | HTTP 404 | `c2znc945zrjyxek9adoset3bu5fh...` |
| 64110 | sicoob_2026_02_26_13_51_32.pdf | application/pdf | HTTP 404 | `kakj9m827j14t9iefac15ui39lia...` |

---

## 📁 Arquivos Gerados

- **JSON completo**: `check_s3_attachments_20260514_093324.json`
- **Markdown (este arquivo)**: `check_s3_attachments_20260514_093324.md`

---

*Gerado por `scripts/check_s3_attachments.py` em 2026-05-14T09:33:24.977201*
