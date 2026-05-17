# YouTube API Audit Form — Respostas pré-preenchidas

> Mantenha esse arquivo aberto e copie campo por campo conforme o form pergunta.
> Antes de começar: pegue seu **Project ID** e **Project Number** em
> https://console.cloud.google.com/home/dashboard

---

## 🔑 Dados básicos (1ª seção)

**Project ID:**
```
[COLA AQUI ANTES DE COMEÇAR — pega em https://console.cloud.google.com/home/dashboard]
```

**Project Number:**
```
[COLA AQUI — mesma página, abaixo do ID]
```

**Application name:**
```
14 Garras Auto-Publisher
```

**Application URL / Website:**
```
https://www.youtube.com/channel/UCGXNSUQTScWqdN7Rfhkbg2A
```

**Privacy Policy URL:**
```
[URL DEPOIS DE PUBLICAR — ex: https://unlucky-jon.github.io/canal-cortes/legal/privacy-policy.html]
```

**Terms of Service URL:**
```
[URL DEPOIS DE PUBLICAR — ex: https://unlucky-jon.github.io/canal-cortes/legal/terms-of-service.html]
```

**Contact email:**
```
jonatas.freire.prof@gmail.com
```

**Channel ID (YouTube channel you operate):**
```
UCGXNSUQTScWqdN7Rfhkbg2A
```

---

## 📂 Tipo da aplicação

- ☑ Web application
- ☑ Desktop / CLI (se a opção existir)
- ☑ **Internal use only** (single channel)
- ☐ Mobile / SaaS / Public-facing / Commercial

---

## 🔌 APIs usados

- ☑ videos.insert
- ☑ videos.list
- ☑ thumbnails.set
- ☑ channels.list
- ☐ liveBroadcasts / comments / subscriptions / playlists

**OAuth scopes:**
```
https://www.googleapis.com/auth/youtube.upload
https://www.googleapis.com/auth/youtube.readonly
```

---

## 📝 Descrição da aplicação (300-500 palavras)

```
14 Garras Auto-Publisher is a single-channel internal automation tool operated by the channel owner to publish cuts of authorized podcast content to the YouTube channel "14 Garras" (UCGXNSUQTScWqdN7Rfhkbg2A).

The tool runs on the operator's local machine and processes long-form podcast videos (with explicit authorization from the source channels) into shorter clips suitable for both YouTube Shorts and standard long-form video formats.

Workflow:
1. The operator provides a YouTube URL of a source video for which they have content authorization.
2. The Application downloads the source (via yt-dlp), transcribes it locally using faster-whisper, and uses AI analysis (Claude) to identify segments with high viewer engagement potential.
3. ffmpeg renders each cut with custom subtitles, end-card branding, and aspect ratio adjustments.
4. For long-form cuts, Gemini API generates a custom 1280x720 thumbnail using extracted speaker faces.
5. The finished cuts are uploaded to YouTube via videos.insert with privacyStatus=private and publishAt set to future scheduled timestamps. YouTube natively handles publication transitions.
6. The Application then closes — no daemon, no background processes.

The Application has NO end users other than the operator. It does not accept input from any third party. It does not serve any public web interface. All authentication is via OAuth 2.0 to the operator's own Google account.

The Application complies with YouTube's Terms of Service:
- Uses publishAt for native scheduling (does not simulate user activity)
- Does not artificially inflate views, likes, subscribers, or comments
- Does not scrape content from other channels
- Operates only on source material with explicit reuse authorization
- Respects all rate limits and quotas
```

---

## 🎯 Justificativa do aumento de quota

```
14 Garras is a Brazilian podcast cuts channel. To grow to YouTube Partner Program eligibility (1k subscribers + 10M Shorts views in 90 days), the channel requires daily publication of 4-5 Shorts plus 1-2 long-form videos.

At default 10,000 units/day quota, videos.insert (1,600 units each) allows only 6 uploads/day with no margin for retries or read operations.

We request 50,000 units/day to enable:
- Theoretical capacity of ~30 uploads/day
- Actual planned usage: 6-8 uploads/day
- Margin for transient retry on network failures
- Headroom for videos.list status verification

Single-channel use. All operations target only the 14 Garras channel (UCGXNSUQTScWqdN7Rfhkbg2A) via OAuth 2.0 authenticated as the channel owner.
```

---

## 🖥️ Onde rodam as APIs?

- ☑ **Server-side / backend** (Python script local com OAuth refresh token)

---

## 👥 Autenticação

```
Single user (the channel owner). OAuth 2.0 Desktop App flow.
Initial authorization opens browser for the operator to log in with their Google account. Refresh token stored locally in token.json (gitignored). No other users authenticated. Token revocable at https://myaccount.google.com/permissions
```

---

## 📊 Quantidade de usuários esperada

```
1 (one — the channel operator).
```

---

## 💰 Comercial?

```
The Application itself is NOT sold, licensed, or distributed to third parties. It is an internal automation tool for the operator's own channel.

The CHANNEL (14 Garras) plans to monetize through YouTube Partner Program ad revenue once eligible.
```

---

## 🎬 Tipo de conteúdo dos vídeos

```
Cuts (short and long-form clips) extracted from podcast episodes for which the operator has explicit re-publication authorization from the source channel. All cuts attribute the source via the description field with a link to the original podcast video.
```

---

## 🔐 Token storage

```
OAuth refresh token stored locally on the operator's machine in token.json (gitignored from the source repository). The client_secret.json is also local-only. No tokens or credentials for any third party are stored.
```

---

## ✅ Compliance checkboxes

- ☑ I will not artificially inflate views, likes, subscribers, comments
- ☑ I will not scrape, store, or republish data from other YouTube channels
- ☑ I will respect all YouTube Data API rate limits and quotas
- ☑ I have read and agree to the YouTube API Services Terms of Service
- ☑ I have read and agree to the YouTube API Services Developer Policies
- ☑ I provide a valid Privacy Policy URL
- ☑ I provide a valid Terms of Service URL
- ☑ I will not impersonate any user or channel
- ☑ The application complies with YouTube Community Guidelines
- ☑ The application does not bypass paywalls or restricted content

---

## 💬 Como você previne abuso?

```
The Application has a built-in quota tracker (SQLite-backed table youtube_quota) that records each videos.insert and thumbnails.set call. Before any upload, it checks remaining daily quota and refuses to make the call if the safety margin would be exceeded.

Additionally, the publication policy is config-driven (config.yaml) and capped at 6 uploads/day in the default configuration to stay within free-tier limits.
```

---

## 📈 Volume estimado por dia

```
Average: 8,000-12,000 units/day
Peak: 15,000-20,000 units/day (uploading backlog after pause)

Breakdown:
- videos.insert: 5-8 uploads × 1,600 units = 8,000-12,800 units
- thumbnails.set: 3 thumbnails × 50 units = 150 units
- videos.list (read): 5-10 calls × 1 unit = 5-10 units
```

---

## ✔️ Checklist antes de Submit

- [ ] Privacy Policy URL abre no browser (200 OK)
- [ ] Terms of Service URL abre no browser (200 OK)
- [ ] Project ID e Number conferem
- [ ] Email de contato correto (vai receber resposta aqui)
- [ ] Channel ID correto

---

## 📧 Após submeter

- Confirmação por email em minutos
- Resposta real em **3-21 dias** (média ~10)
- Possíveis respostas:
  - ✅ **Aprovado**: aumento aplicado, conferir no Cloud Console
  - 🟡 **Pedem mais info**: respondem com lista específica → responda em até 7 dias
  - ❌ **Negado** (raro pra single-channel): refaça enfatizando uso pessoal único

Se demorar mais de 21 dias, mande follow-up no mesmo thread.
