<?php
session_start();

define('URL_STEP1', 'https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/searchApplicationOnlineIndex.faces');
define('URL_STEP2', 'https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/applicationOnlineIndex.faces');

$result = [];
$error = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST' && !empty($_POST['national_id'])) {
    $nationalId = trim($_POST['national_id']);
    $cookieFile = sys_get_temp_dir() . '/vision_cookie_' . session_id() . '.txt';

    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_COOKIEJAR => $cookieFile,
        CURLOPT_COOKIEFILE => $cookieFile,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_USERAGENT => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        CURLOPT_TIMEOUT => 30,
    ]);

    curl_setopt($ch, CURLOPT_URL, URL_STEP1);
    curl_setopt($ch, CURLOPT_HTTPGET, true);
    $response1 = curl_exec($ch);
    $httpCode1 = curl_getinfo($ch, CURLINFO_HTTP_CODE);

    if ($response1 === false || $httpCode1 !== 200) {
        $error = 'فشل الاتصال بالصفحة الأولى: ' . curl_error($ch);
    } else {
        curl_setopt($ch, CURLOPT_URL, URL_STEP2);
        curl_setopt($ch, CURLOPT_HTTPGET, true);
        $response2 = curl_exec($ch);
        $httpCode2 = curl_getinfo($ch, CURLINFO_HTTP_CODE);

        if ($response2 === false || $httpCode2 !== 200) {
            $error = 'فشل الاتصال بالصفحة الثانية: ' . curl_error($ch);
        } else {
            $viewState = '';
            if (preg_match('/<input[^>]*name="(?:javax|jakarta)\.faces\.ViewState"[^>]*value="([^"]*)"/i', $response2, $m)) {
                $viewState = $m[1];
            }

            $formAction = URL_STEP2;
            if (preg_match('/<form[^>]*action="([^"]*)"/i', $response2, $m)) {
                $formAction = $m[1];
                if (!str_starts_with($formAction, 'http')) {
                    $parsed = parse_url(URL_STEP2);
                    $formAction = $parsed['scheme'] . '://' . $parsed['host'] . $formAction;
                }
            }

            $postFields = [
                'javax.faces.ViewState' => $viewState,
                'myForm' => 'myForm',
                'myForm:nationalNo' => $nationalId,
                'myForm:retriveQiyasAPIData' => 'myForm:retriveQiyasAPIData',
            ];

            curl_setopt($ch, CURLOPT_URL, $formAction);
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($postFields, '', '&'));
            $response3 = curl_exec($ch);
            $httpCode3 = curl_getinfo($ch, CURLINFO_HTTP_CODE);

            if ($response3 === false || $httpCode3 !== 200) {
                $error = 'فشل إرسال البيانات: ' . curl_error($ch);
            } else {
                $body = $response3;

                $patterns = [
                    'first_name' => ['myForm:fnames'],
                    'father_name' => ['myForm:fatherNames'],
                    'grand_name' => ['myForm:grandNames'],
                    'family_name' => ['myForm:familyNames'],
                    'capabilities' => ['myForm:capabilities'],
                    'tah_score' => ['myForm:tahselMark'],
                ];

                foreach ($patterns as $key => $pats) {
                    foreach ($pats as $pat) {
                        if (preg_match('/<input[^>]*(?:id|name)="[^"]*' . preg_quote($pat, '/') . '[^"]*"[^>]*value="([^"]*)"/i', $body, $m)) {
                            $val = trim($m[1]);
                            if ($val !== '') {
                                $result[$key] = $val;
                                break;
                            }
                        }
                        if (preg_match('/<td[^>]*>\s*' . preg_quote($pat, '/') . '\s*<\/td>\s*<td[^>]*>\s*<input[^>]*value="([^"]*)"[^>]*>/i', $body, $m)) {
                            $val = trim($m[1]);
                            if ($val !== '') {
                                $result[$key] = $val;
                                break;
                            }
                        }
                    }
                }

                $parts = [];
                foreach (['first_name', 'father_name', 'grand_name', 'family_name'] as $part) {
                    if (!empty($result[$part])) {
                        $parts[] = $result[$part];
                    }
                }
                $result['full_name'] = implode(' ', $parts);
            }
        }
    }

    curl_close($ch);
    if (file_exists($cookieFile)) unlink($cookieFile);
}
?>
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>الاستعلام عن النتائج</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;500;600;700;800;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Cairo','Segoe UI',Arial,sans-serif;background:#000;min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px;position:relative;overflow-x:hidden}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(circle at 50% 0%,rgba(59,130,246,0.08) 0%,transparent 60%);z-index:0}
.orb{position:fixed;border-radius:50%;filter:blur(100px);z-index:0;animation:orbFloat 25s ease-in-out infinite}
.orb:nth-child(1){width:500px;height:500px;background:rgba(59,130,246,0.08);top:-150px;right:-100px}
.orb:nth-child(2){width:400px;height:400px;background:rgba(6,182,212,0.06);bottom:-120px;left:-100px;animation-delay:-8s}
.orb:nth-child(3){width:250px;height:250px;background:rgba(59,130,246,0.05);top:40%;left:5%;animation-delay:-16s}
@keyframes orbFloat{0%,100%{transform:translate(0,0) scale(1)}25%{transform:translate(40px,-50px) scale(1.05)}50%{transform:translate(-20px,30px) scale(0.95)}75%{transform:translate(30px,40px) scale(1.02)}}
.container{position:relative;z-index:1;background:rgba(255,255,255,0.04);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);border-radius:32px;box-shadow:0 8px 32px rgba(0,0,0,0.4),0 0 0 1px rgba(255,255,255,0.06);padding:50px 45px;width:100%;max-width:520px;transition:all 0.4s}
h1{font-size:26px;font-weight:900;color:#fff;margin-bottom:6px;text-align:center}
h1::after{content:'';display:block;width:50px;height:3px;background:#3b82f6;border-radius:3px;margin:10px auto 0}
.subtitle{color:#a0aec0;font-size:14px;margin:6px 0 32px;text-align:center}
label{display:block;font-weight:600;color:#cbd5e0;margin-bottom:10px;font-size:13px}
input[type="text"]{width:100%;padding:16px 18px;border:1px solid rgba(255,255,255,0.1);border-radius:16px;font-size:20px;font-family:'Cairo',sans-serif;font-weight:700;letter-spacing:3px;direction:ltr;text-align:center;transition:all 0.35s;background:rgba(255,255,255,0.05);color:#fff}
input[type="text"]:hover{border-color:rgba(59,130,246,0.3);background:rgba(255,255,255,0.07)}
input[type="text"]:focus{outline:none;border-color:#3b82f6;box-shadow:0 0 0 4px rgba(59,130,246,0.15);background:rgba(255,255,255,0.08)}
button{width:100%;padding:16px;background:linear-gradient(135deg,#2563eb,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:16px;font-size:16px;font-weight:700;font-family:'Cairo',sans-serif;cursor:pointer;transition:all 0.3s;margin-top:8px}
button:hover{transform:scale(1.015)}
button:disabled{opacity:0.6;cursor:not-allowed;transform:none}
.error{background:rgba(239,68,68,0.1);color:#f87171;padding:16px 20px;border-radius:16px;margin-top:22px;font-size:14px;text-align:center;font-weight:500;border:1px solid rgba(239,68,68,0.2)}
.result{margin-top:30px;background:rgba(255,255,255,0.04);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-radius:24px;padding:28px;border:1px solid rgba(255,255,255,0.06)}
.result::before{content:'';display:block;height:3px;background:linear-gradient(90deg,#2563eb,#3b82f6,#06b6d4);border-radius:24px 24px 0 0;margin:-28px -28px 20px}
.result h2{font-size:24px;font-weight:900;color:#fff;text-align:center;padding-bottom:18px;border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:18px}
.score-section{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.score-card{border-radius:18px;padding:18px 14px;text-align:center;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06)}
.score-card .score-label{font-size:12px;font-weight:600;color:#a0aec0;margin-bottom:6px}
.score-card .score-value{font-size:32px;font-weight:900;color:#fff}
.score-card.tahsili .score-value{color:#22c55e}
.loading{display:none;text-align:center;margin-top:20px;color:#3b82f6;font-weight:600}
.loading.active{display:block}
.footer{text-align:center;margin-top:24px;font-size:12px;color:#6b7280}
.footer a{color:#6b7280;text-decoration:none}
.footer a:hover{color:#3b82f6}
@media(max-width:480px){body{padding:12px}.container{padding:24px 16px;border-radius:24px}h1{font-size:20px}.score-section{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="orb"></div><div class="orb"></div><div class="orb"></div>
<div class="container">
<h1>الاستعلام عن النتائج</h1>
<p class="subtitle">أدخل رقم الهوية للاستعلام عن الاسم ودرجات القدرات والتحصيلي</p>

<form method="post" id="searchForm">
<label for="national_id">رقم الهوية</label>
<input type="text" id="national_id" name="national_id" required placeholder="" value="<?= htmlspecialchars($_POST['national_id'] ?? '') ?>" maxlength="10" autofocus>
<button type="submit" id="submitBtn">بحث</button>
</form>

<div class="loading" id="loading">جاري البحث...</div>

<?php if (!empty($error)): ?>
<div class="error"><?= htmlspecialchars($error) ?></div>
<?php endif; ?>

<?php if (!empty($result)): ?>
<div class="result">
<h2><?= htmlspecialchars($result['full_name'] ?: 'النتيجة') ?></h2>
<div class="score-section">
<div class="score-card capabilities"><div class="score-label">القدرات</div><div class="score-value"><?= htmlspecialchars($result['capabilities'] ?? '—') ?></div></div>
<div class="score-card tahsili"><div class="score-label">التحصيلي</div><div class="score-value"><?= htmlspecialchars($result['tah_score'] ?? '—') ?></div></div>
</div>
</div>
<?php endif; ?>

<div class="footer">
Developed By vovo <span style="color:#ef4444">&#10084;</span>
<a href="https://www.instagram.com/tnnd" target="_blank"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:middle;margin-right:4px"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/></svg></a>
</div>
</div>

<script>
document.getElementById('searchForm')?.addEventListener('submit',function(){
document.getElementById('submitBtn').disabled=true;
document.getElementById('loading').classList.add('active');
});
</script>
</body>
</html>
