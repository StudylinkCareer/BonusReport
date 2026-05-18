-- ============================================================================
-- Migration 14l — Set demo passwords for all 14 seed users
-- ============================================================================
-- Password: demo1234  (all users)
--
-- Hash format: pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
--   - Algorithm: PBKDF2-HMAC-SHA256 (Python hashlib.pbkdf2_hmac, stdlib only)
--   - Iterations: 600,000 (OWASP 2023 recommendation)
--   - Salt: 16 random bytes per user (unique salt — proper practice)
--   - Hash: 32 bytes (default SHA-256 output)
--
-- Verification in Block 2 (FastAPI auth module) uses the same hashlib
-- function — no third-party packages required for password operations.
--
-- Idempotent — re-running just overwrites with fresh hashes (same password,
-- different salts, all verify identically).
-- ============================================================================

BEGIN;

UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$rG91+W636vofWfOvx9PZdQ$GAPHyvmH47aI/UtQDnzoty1r17kD5Dwu3GTUNtk6g2s', updated_at = NOW() WHERE email = 'director@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$/QWpFFl/5S8P6iiE5XzPrg$AxhnZRuEKtVNsawLy2mWUYq5Q1NvQg210Ot4tm6D4VA', updated_at = NOW() WHERE email = 'admin@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$bSr4hiJOcJAOrWaLe46Xew$TYzevk9jn9Pyaxv7x9BGQ4tSCEfo8vw7pbcpM1Rtj+I', updated_at = NOW() WHERE email = 'fo@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$271JWdUxzgh2AEOHzy+Yig$IgsonPYlFsKWcXYiseekpGVKjUK/URGsYRTvAwJgezg', updated_at = NOW() WHERE email = 'dqo@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$ItpmI51FEUSq8gW6B0YCbA$WKbn1W7gLeBiDa0VF+AsHeESUz4spzQs3t0299xyCRM', updated_at = NOW() WHERE email = 'loi@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$u8cQ6rmOWaVxE+gJ8zK+jg$9y5qxDz+goi142mxuc/g0T+mPKUpwIUrvERVr6NnIm0', updated_at = NOW() WHERE email = 'truongan@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$kKi9cdttDJhxKEQKWSA9Rw$x/VFw4uNZOGPz+oYoSostMexL0tD/IxuJnyXirWafb8', updated_at = NOW() WHERE email = 'hoangyen@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$I4US7/0flOEwEgzBmuP0xw$X1TvGzmoSVBpxI/G5dpgGk3ohcormh95DImJjNG5r4Y', updated_at = NOW() WHERE email = 'trucquynh@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$iTN/HwmhrXmVzCTUBf/BTg$1RNi/hVeboGEysSv7y3MbSjTYjyqCDO4BbFcemDolOg', updated_at = NOW() WHERE email = 'giaman@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$W/1MPNMxTeflbr8AQ954vw$TmpcNyNyIQeiShHUjoYD+QXLpjU1ubDEMs61ZomOhoQ', updated_at = NOW() WHERE email = 'vinh@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$i3ZretFSYFAvbvxQkouCyQ$s4zjDFCSkH7Pn+nZ6AnS/R3tOGjTZ66Qhj7moygSBko', updated_at = NOW() WHERE email = 'myly@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$IKci85snUB8SqsJ9PnEikA$QzXBnpWnsLCrBmZJ1pchSaT0hcpNaCFVZFvMfTvTt1E', updated_at = NOW() WHERE email = 'honghanh@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$LvLoEJn37pDk/JT2tc/J7g$N7+mm3Adjo2PK72XxTbamP9sQVnDkoxjbckv30KJIKw', updated_at = NOW() WHERE email = 'khietoanh@studylink.test';
UPDATE app_user SET password_hash = 'pbkdf2_sha256$600000$j/YxVcQeJWgr4H8zCIZotA$ae4cyqgUOcJn8HiuevByP4qSzolVYQtirC2oNRerylA', updated_at = NOW() WHERE email = 'tatthanh@studylink.test';

COMMIT;

-- ============================================================================
-- Verification — expect 14 rows, all with password_status = 'set'
-- ============================================================================

SELECT email, display_name,
       CASE WHEN password_hash IS NULL THEN 'NOT SET' ELSE 'set' END AS password_status,
       SPLIT_PART(password_hash, '$', 1) AS hash_algorithm,
       SPLIT_PART(password_hash, '$', 2) AS iterations
FROM app_user
WHERE email LIKE '%@studylink.test'
ORDER BY email;