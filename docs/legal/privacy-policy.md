# Privacy Policy — 14 Garras Auto-Publisher

**Effective date:** 2026-05-17
**Operator:** Jonatas Pereira (`jonatas.freire.prof@gmail.com`)

## 1. Overview

14 Garras Auto-Publisher (the "Application") is a single-user, single-channel
internal automation tool used exclusively by the operator to manage publications
on the YouTube channel **14 Garras**
(`UCGXNSUQTScWqdN7Rfhkbg2A`).

The Application has **no end users** other than the operator.

## 2. Data Collected

The Application accesses the following data via Google APIs, **scoped to the
operator's own Google account**:

- **YouTube Data API v3** (videos.insert, thumbnails.set, channels.list,
  videos.list): used to publish videos and verify status on the operator's
  own channel.
- **Gemini API** (image generation): used to create thumbnails. No user data
  is sent — only video frames captured from source content already authorized
  by the operator.

No data from any other user is collected, stored, or shared.

## 3. Storage

- Local SQLite database on the operator's machine stores: cut metadata,
  publication schedule, and YouTube video IDs of published cuts.
- No data is transmitted to any third party beyond YouTube and Gemini API
  endpoints required for operation.

## 4. Third-Party Services

The Application interacts with:
- **Google YouTube Data API v3** (Google's privacy policy applies:
  https://policies.google.com/privacy)
- **Google Gemini API** (Google's privacy policy applies)
- **Anthropic Claude API** (Anthropic's privacy policy:
  https://www.anthropic.com/privacy)

## 5. Source Content Authorization

The Application is operated only on source video content for which the
operator holds explicit authorization (own content, or content licensed for
re-publication).

## 6. Data Retention

OAuth credentials and tokens are stored locally on the operator's machine
only. They can be revoked at any time at https://myaccount.google.com/permissions.

## 7. Contact

For any questions regarding this policy:
- Email: jonatas.freire.prof@gmail.com
- Channel: https://www.youtube.com/channel/UCGXNSUQTScWqdN7Rfhkbg2A

## 8. Changes

This policy may be updated. Updates will be posted to this URL.
