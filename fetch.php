<?php
/**
 * fetch.php — Vision Gate Student Lookup
 * منطق مطابق للكود الأصلي (Python/Pythonista)
 *
 * التدفق:
 *  1. GET  URL_STEP1  ← session init + ViewState
 *  2. GET  URL_STEP2  ← تحديث ViewState من الصفحة الثانية
 *  3. POST URL_STEP2  ← AJAX partial/ajax بـ myForm:nationalNo
 *  4. GET  URL_STEP2  ← جلب الصفحة الكاملة بعد الـ AJAX
 *  5. parse البيانات بنفس FIELD_PATTERNS + _format_score_2dp
 */

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    echo json_encode(['error' => 'Method not allowed'], JSON_UNESCAPED_UNICODE);
    exit;
}

define('URL_STEP1', 'https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/searchApplicationOnlineIndex.faces');
define('URL_STEP2', 'https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/applicationOnlineIndex.faces');
define('UA',        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');

// ── التحقق من المدخلات ──────────────────────────────────────
$raw = json_decode(file_get_contents('php://input'), true);
$nid = preg_replace('/\D/', '', $raw['id'] ?? '');

if (!preg_match('/^\d{10}$/', $nid)) {
    echo json_encode(['error' => 'رقم الهوية يجب أن يكون 10 أرقام بالضبط'], JSON_UNESCAPED_UNICODE);
    exit;
}

// ── مساعد cURL ──────────────────────────────────────────────
function doRequest(string $url, string $cookieJar, array $extra = []): string {
    $ch = curl_init();
    curl_setopt_array($ch, array_replace([
        CURLOPT_URL            => $url,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_COOKIEJAR      => $cookieJar,
        CURLOPT_COOKIEFILE     => $cookieJar,
        CURLOPT_USERAGENT      => UA,
        CURLOPT_ENCODING       => '',       // auto gzip
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_HTTPHEADER     => [
            'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language: ar,en-US;q=0.9,en;q=0.8',
            'Connection: keep-alive',
        ],
    ], $extra));
    $out = curl_exec($ch) ?: '';
    curl_close($ch);
    return $out;
}

// يستخرج ViewState من HTML
function getViewState(string $html): string {
    foreach ([
        '/<input[^>]+name="javax\.faces\.ViewState"[^>]+value="([^"]+)"/i',
        '/<input[^>]+value="([^"]+)"[^>]+name="javax\.faces\.ViewState"/i',
    ] as $rx) {
        if (preg_match($rx, $html, $m)) return $m[1];
    }
    return '';
}

// يستخرج form id من HTML
function getFormId(string $html): string {
    if (preg_match('/<form[^>]+id="([^"]+)"/i', $html, $m)) return $m[1];
    return 'myForm';
}

// ── STEP 1: الصفحة الأولى ───────────────────────────────────
$jar   = tempnam(sys_get_temp_dir(), 'vg_');
$html1 = doRequest(URL_STEP1, $jar);
if (!$html1) {
    @unlink($jar);
    echo json_encode(['error' => 'فشل الاتصال بالموقع (الخطوة 1)'], JSON_UNESCAPED_UNICODE);
    exit;
}
$viewState = getViewState($html1);
$formId    = getFormId($html1);

// ── STEP 2: GET الصفحة الثانية لتهيئة الجلسة ───────────────
$html2 = doRequest(URL_STEP2, $jar, [
    CURLOPT_HTTPHEADER => [
        'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language: ar,en-US;q=0.9,en;q=0.8',
        'Referer: ' . URL_STEP1,
        'Connection: keep-alive',
    ],
]);
if ($html2) {
    if (($vs = getViewState($html2)) !== '') $viewState = $vs;
    if (($fi = getFormId($html2))    !== 'myForm') $formId = $fi;
}

// ── STEP 3: POST AJAX — تعبئة myForm:nationalNo ─────────────
// (مطابق لما يفعله eval_js في الكود الأصلي)
$ajaxFields = http_build_query([
    'javax.faces.partial.ajax'    => 'true',
    'javax.faces.source'          => $formId . ':nationalNo',
    'javax.faces.partial.execute' => $formId . ':nationalNo',
    'javax.faces.partial.render'  => '@all',
    $formId                       => $formId,
    $formId . ':nationalNo'       => $nid,
    'javax.faces.ViewState'       => $viewState,
]);

$ajaxResp = doRequest(URL_STEP2, $jar, [
    CURLOPT_POST       => true,
    CURLOPT_POSTFIELDS => $ajaxFields,
    CURLOPT_HTTPHEADER => [
        'Accept: application/xml, text/xml, */*; q=0.01',
        'Accept-Language: ar,en-US;q=0.9,en;q=0.8',
        'Content-Type: application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With: XMLHttpRequest',
        'Faces-Request: partial/ajax',
        'Referer: ' . URL_STEP2,
        'Origin: https://gate.vision.edu.sa',
    ],
]);

// ── STEP 4: GET الصفحة الكاملة بعد الـ AJAX ─────────────────
// (مثل document.documentElement.outerHTML بعد FINAL_WAIT_SEC)
$finalHtml = doRequest(URL_STEP2, $jar, [
    CURLOPT_HTTPHEADER => [
        'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language: ar,en-US;q=0.9,en;q=0.8',
        'Referer: ' . URL_STEP2,
        'Connection: keep-alive',
    ],
]);

@unlink($jar);

// نختار أفضل HTML للمعالجة
$html = $finalHtml ?: ($ajaxResp ?: $html2 ?: '');
if (!$html) {
    echo json_encode(['error' => 'لم يتم استلام أي بيانات من الموقع'], JSON_UNESCAPED_UNICODE);
    exit;
}

// ── استخراج قيمة حقل ────────────────────────────────────────
// (مطابق لـ FormIndexer.get_value + DataExtractor._find)
function extractField(string $html, array $patterns): string {
    foreach ($patterns as $p) {
        // input value=
        if (preg_match(
            '/<input(?=[^>]*(?:name|id)="' . $p . '")[^>]*\bvalue="([^"]*)"/i',
            $html, $m
        ) && $m[1] !== '') {
            return html_entity_decode(trim($m[1]), ENT_QUOTES | ENT_HTML5, 'UTF-8');
        }
        // input reversed: value= before name/id
        if (preg_match(
            '/<input(?=[^>]*\bvalue="([^"]+)")[^>]*(?:name|id)="' . $p . '"[^>]*>/i',
            $html, $m
        )) {
            return html_entity_decode(trim($m[1]), ENT_QUOTES | ENT_HTML5, 'UTF-8');
        }
        // select: option[selected]
        if (preg_match(
            '/<select(?=[^>]*(?:name|id)="' . $p . '")[^>]*>(.*?)<\/select>/is',
            $html, $sm
        )) {
            if (preg_match('/<option[^>]+selected[^>]*>\s*([^<]+)\s*<\/option>/i', $sm[1], $om)) {
                $v = html_entity_decode(trim($om[1]), ENT_QUOTES | ENT_HTML5, 'UTF-8');
                if ($v !== '') return $v;
            }
        }
        // نص بعد td/span/div يحتوي الـ pattern (fallback)
        if (preg_match(
            '/(?:' . $p . ')[^>]{0,60}>\s*<[^>]+>\s*([^\s<][^<]{1,80}?)\s*</iu',
            $html, $tm
        )) {
            $v = html_entity_decode(trim($tm[1]), ENT_QUOTES | ENT_HTML5, 'UTF-8');
            if ($v !== '' && !preg_match('/[<>{}]/', $v)) return $v;
        }
    }
    return '';
}

// ── تطبيع الدرجة (مطابق لـ _format_score_2dp) ───────────────
function formatScore(string $raw): string {
    if ($raw === '') return '';
    if (!preg_match('/(\d+(?:[.,]\d+)?)/', $raw, $m)) return '';
    $n = (float) str_replace(',', '.', $m[1]);
    while ($n > 100 && $n <= 10000) $n /= 100.0;
    $n = max(0.0, min(100.0, $n));
    return number_format($n, 2, '.', '');
}

// ── FIELD_PATTERNS (مطابق تماماً للكود الأصلي) ──────────────
$FIELDS = [
    'first_name'  => ['(?:myForm:)?fnames',     'first.?name',  'الاسم.?الأول',  'الاسم.?الاول'],
    'father_name' => ['(?:myForm:)?fatherNames', 'father.?name', 'اسم.?الأب',     'اسم.?الاب'],
    'grand_name'  => ['(?:myForm:)?grandNames',  'grand.?name',  'اسم.?الجد'],
    'family_name' => ['(?:myForm:)?familyNames', 'family.?name', 'اسم.?العائلة',  'اللقب'],
    'cap_score'   => ['(?:myForm:)?capabilities','قدرات',        'qiyas',          'قياس'],
    'tah_score'   => ['(?:myForm:)?tahselMark',  'تحصيلي'],
];

$data = [];
foreach ($FIELDS as $key => $patterns) {
    $data[$key] = extractField($html, $patterns);
}
$data['cap_score'] = formatScore($data['cap_score']);
$data['tah_score'] = formatScore($data['tah_score']);

// ── extract_sa_id (مطابق للكود الأصلي) ─────────────────────
$extractedId = '';
if (preg_match(
    '/<input(?=[^>]*(?:name|id)="(?:myForm:)?(?:nationalNo|nationalId|idNumber)")[^>]*\bvalue="(\d{10})"/i',
    $html, $m
)) {
    $extractedId = $m[1];
} elseif (preg_match('/(?<!\d)(\d{10})(?!\d)/', $html, $m)) {
    $extractedId = $m[1];
}

// ── الجنسية من رقم الهوية ───────────────────────────────────
$nationality = 'غير متوفر';
if ($nid[0] === '1') $nationality = 'السعودية';
elseif ($nid[0] === '2') $nationality = 'غير سعودي / مقيم';

// ── بناء الاسم الكامل ───────────────────────────────────────
$parts    = array_filter([$data['first_name'], $data['father_name'], $data['grand_name'], $data['family_name']]);
$fullName = implode(' ', $parts) ?: '';

// ── التحقق من وجود بيانات ───────────────────────────────────
$hasData  = $fullName !== '' || $data['cap_score'] !== '' || $data['tah_score'] !== '';

if (!$hasData) {
    $idFound = ($extractedId === $nid) || str_contains($html, $nid);
    echo json_encode([
        'error' => $idFound
            ? 'تم العثور على الهوية لكن البيانات غير مكتملة بعد، حاول مجدداً'
            : 'رقم الهوية غير موجود في النظام أو لم يتم التسجيل بعد',
    ], JSON_UNESCAPED_UNICODE);
    exit;
}

// ── الاستجابة النهائية ───────────────────────────────────────
echo json_encode([
    'success' => true,
    'data' => [
        'id'          => $nid,
        'nationality' => $nationality,
        'first_name'  => $data['first_name']  ?: 'غير متوفر',
        'father_name' => $data['father_name'] ?: 'غير متوفر',
        'grand_name'  => $data['grand_name']  ?: 'غير متوفر',
        'family_name' => $data['family_name'] ?: 'غير متوفر',
        'full_name'   => $fullName            ?: 'غير متوفر',
        'cap_score'   => $data['cap_score']   ?: 'لم يختبر بعد',
        'tah_score'   => $data['tah_score']   ?: 'لم يختبر بعد',
    ],
], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);