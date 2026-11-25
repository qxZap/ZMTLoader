// ZMT Loader -- plugins\mt_plugin_ZMTLoader.dll.
//
// Finds the data tables the installed mods add and makes them parents of the DataTable Framework's composites, in
// memory, at startup. Names no mod.
//
//   1. fingerprint = SHA-256 over the sorted Content\Paks\*.pak list (name, size, mtime); cache in
//      plugins\zmt_loader_cache.json. Same fingerprint -> reuse the cached plan, else scan and plan.
//   2. plan (planTables, pure -- mirrored in tools\zmt_loader_test.py): per framework composite, every loaded plain
//      DataTable with its row struct that no composite lists (directly or through a nested one).
//   3. apply on the game thread: new ParentTables buffer from the engine (GetDataTableRowNames' output array), then the
//      composite's own OnParentTablesUpdated(composite, 1) rebuilds the rows. A drop in row count reverts the change.
// Tables nothing references are never loaded, so before scanning the plugin reads the file index of every mod pak
// (not the game's, not the framework's), takes the /Game/DataAsset/*.uasset paths and loads those not loaded yet, in
// batches on the game thread; the planner then sees them. A dedicated server has no player: it waits for a GameState
// and framework composites with rows instead. DryRun=1 still loads them (the plan needs them), it changes no composite.
// The plan that ran goes to plugins\logs\ZMTLoader\plan_<sha>.json. [AutoPatch] DryRun=1 plans and writes it only.
// Fail safe: anything not found at runtime -> log once, do nothing. Only a framework composite's ParentTables is written.

#include <algorithm>
#include <functional>
#include <map>
#include <set>
#include <unordered_map>
#include <string>
#include <vector>
#include "../include/mt_plugin.hpp"
#include <bcrypt.h>

using namespace mt;
#pragma comment(lib, "bcrypt.lib")

static const wchar_t* INI = L"zmt_loader.ini";
static const char* CACHE_VERSION = "2";   // 2: the cache also holds the discovered candidate paths

// ===================================================================== planner (pure; no engine access)
struct PT {                          // a loaded table
    std::string name, st;            // "pkg.Name", row-struct id
    bool comp = false;
    std::vector<std::string> parents;  // composites only; "" = a null parent
    int mount = 0;                   // load order (object index): later wins, as UE would
};
struct Skip { std::string table, reason; };
struct PC {
    std::string name, st;
    std::vector<std::string> before, added, after;
    std::vector<Skip> skipped;
};

static bool ignoredPkg(const std::string& n) {
    return n.rfind("/Script", 0) == 0 || n.rfind("/Engine", 0) == 0 || n.rfind("/Temp", 0) == 0;
}

static std::vector<PC> planTables(const std::vector<PT>& tables, std::vector<std::string> framework) {
    std::map<std::string, const PT*> by;
    for (auto& t : tables) by[t.name] = &t;
    std::set<std::string> covered;   // listed as a parent of any composite, directly or through a nested one
    std::vector<std::string> stack;
    for (auto& t : tables) if (t.comp) for (auto& p : t.parents) if (!p.empty()) stack.push_back(p);
    while (!stack.empty()) {
        std::string p = stack.back(); stack.pop_back();
        if (!covered.insert(p).second) continue;
        auto it = by.find(p);
        if (it != by.end() && it->second->comp) for (auto& q : it->second->parents) if (!q.empty()) stack.push_back(q);
    }
    std::sort(framework.begin(), framework.end());
    std::vector<const PT*> roots;    // a composite another one lists is a hub, not a target
    for (auto& n : framework) {
        auto it = by.find(n);
        if (it != by.end() && it->second->comp && !covered.count(n)) roots.push_back(it->second);
    }
    std::vector<const PT*> cand;
    for (auto& t : tables) if (!t.comp && !covered.count(t.name) && !ignoredPkg(t.name)) cand.push_back(&t);
    std::sort(cand.begin(), cand.end(), [](const PT* a, const PT* b) {
        return a->mount != b->mount ? a->mount < b->mount : a->name < b->name; });
    std::vector<PC> out;
    for (auto* c : roots) {
        PC r; r.name = c->name; r.st = c->st; r.before = c->parents;
        for (size_t i = 0; i < c->parents.size(); i++) {
            const std::string& p = c->parents[i];
            if (p.empty()) r.skipped.push_back({"(parent #" + std::to_string(i) + ")", "listed, not present"});
            else if (!by.count(p)) r.skipped.push_back({p, "listed, not present"});
        }
        int shared = 0;
        for (auto* o : roots) if (o->st == c->st) shared++;
        for (auto* t : cand) {
            if (t->st != c->st) continue;
            if (shared > 1) r.skipped.push_back({t->name, "row struct shared by " + std::to_string(shared) + " framework composites"});
            else r.added.push_back(t->name);
        }
        r.after = r.before;
        r.after.insert(r.after.end(), r.added.begin(), r.added.end());
        out.push_back(r);
    }
    return out;
}

// ===================================================================== tiny JSON (cache read, plan write)
static std::string esc(const std::string& s) {
    std::string o = "\"";
    for (unsigned char c : s) { if (c == '"' || c == '\\') { o += '\\'; o += (char)c; } else if (c < 0x20) o += ' '; else o += (char)c; }
    return o + "\"";
}
static std::string strList(const std::vector<std::string>& v) {
    std::string o = "[";
    for (size_t i = 0; i < v.size(); i++) o += (i ? "," : "") + (v[i].empty() ? std::string("null") : esc(v[i]));
    return o + "]";
}
struct J { char t = 0; std::string s; std::vector<J> a; std::vector<std::pair<std::string, J>> o; };
static bool parseJ(const std::string& s, size_t& i, J& out) {
    auto ws = [&] { while (i < s.size() && isspace((unsigned char)s[i])) i++; };
    ws();
    if (i >= s.size()) return false;
    if (s[i] == '"') {
        out.t = 's';
        for (i++; i < s.size() && s[i] != '"'; i++) { if (s[i] == '\\' && i + 1 < s.size()) i++; out.s += s[i]; }
        i++; return i <= s.size();
    }
    if (s[i] == '[' || s[i] == '{') {
        bool obj = s[i] == '{'; out.t = obj ? 'o' : 'a'; i++;
        for (;;) {
            ws();
            if (i >= s.size()) return false;
            if (s[i] == (obj ? '}' : ']')) { i++; return true; }
            if (s[i] == ',') { i++; continue; }
            J k, v;
            if (obj) { if (!parseJ(s, i, k)) return false; ws(); if (i >= s.size() || s[i] != ':') return false; i++; }
            if (!parseJ(s, i, v)) return false;
            if (obj) out.o.push_back({k.s, v}); else out.a.push_back(v);
        }
    }
    out.t = 'x';  // number / true / null: skipped
    while (i < s.size() && !strchr(",]} \t\r\n", s[i])) i++;
    return true;
}

// ===================================================================== fingerprint
static std::string sha256hex(const std::string& data) {
    BCRYPT_ALG_HANDLE h = nullptr;
    unsigned char d[32] = {0};
    if (BCryptOpenAlgorithmProvider(&h, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0) return "";
    NTSTATUS st = BCryptHash(h, nullptr, 0, (PUCHAR)data.data(), (ULONG)data.size(), d, 32);
    BCryptCloseAlgorithmProvider(h, 0);
    if (st != 0) return "";
    std::string o;
    for (unsigned char c : d) { char b[3]; snprintf(b, 3, "%02x", c); o += b; }
    return o;
}
static void listPaks(const std::wstring& dir, const std::wstring& rel, std::vector<std::string>& out) {
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        std::wstring n = fd.cFileName;
        if (n == L"." || n == L"..") continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) { listPaks(dir + L"\\" + n, rel + n + L"/", out); continue; }
        if (n.size() < 4 || _wcsicmp(n.c_str() + n.size() - 4, L".pak") != 0) continue;
        std::wstring full = rel + n;
        for (auto& c : full) c = (wchar_t)towlower(c);
        std::string u8(WideCharToMultiByte(CP_UTF8, 0, full.c_str(), -1, nullptr, 0, nullptr, nullptr), 0);
        WideCharToMultiByte(CP_UTF8, 0, full.c_str(), -1, u8.data(), (int)u8.size(), nullptr, nullptr);
        u8.resize(strlen(u8.c_str()));
        unsigned long long size = ((unsigned long long)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
        unsigned long long mt = ((unsigned long long)fd.ftLastWriteTime.dwHighDateTime << 32) | fd.ftLastWriteTime.dwLowDateTime;
        out.push_back(u8 + "|" + std::to_string(size) + "|" + std::to_string(mt));
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}
// Same text in tools\zmt_loader_test.py: "v<version>\n" + sorted "name|size|mtime" lines joined by "\n".
static std::string fingerprint() {
    std::vector<std::string> v;
    listPaks(gameDir() + L"..\\..\\Content\\Paks", L"", v);
    std::sort(v.begin(), v.end());
    std::string t = std::string("v") + CACHE_VERSION;
    for (auto& s : v) t += "\n" + s;
    return sha256hex(t);
}

// ===================================================================== pak index (pure parse; mirrored in the test)
// Pak v8-v11 footer: [guid 16][encrypted 1][magic 4][version 4][index offset 8][index size 8]... -> found by the magic,
// so the footer's trailing size (it grew with each version) does not matter.
struct Rd {
    const uint8_t* p; size_t n, i = 0; bool bad = false;
    template <class T> T get() { T v{}; if (i + sizeof(T) > n) { bad = true; return v; } memcpy(&v, p + i, sizeof(T)); i += sizeof(T); return v; }
    void skip(size_t k) { if (k > n - i) { bad = true; i = n; } else i += k; }
    std::string fstr() {
        int32_t len = get<int32_t>();
        if (bad || len == 0) return "";
        if (len > 0) { if ((size_t)len > n - i) { bad = true; return ""; } std::string s((const char*)p + i, len - 1); i += len; return s; }
        if (len < -0x100000 || (size_t)(-len) * 2 > n - i) { bad = true; return ""; }
        std::string s; for (int k = 0; k < -len - 1; k++) { uint16_t c = get<uint16_t>(); s += c < 0x80 ? (char)c : '?'; }
        skip(2); return s;
    }
};
// "../../../MotorTown/Content/" + "DataAsset/X/Y.uasset" -> "/Game/DataAsset/X/Y.Y"; "" for anything else.
static std::string gamePathOf(std::string full) {
    for (auto& c : full) if (c == '\\') c = '/';
    std::string t;   // collapse "//"
    for (char c : full) if (!(c == '/' && !t.empty() && t.back() == '/')) t += c;
    std::string low = t; for (auto& c : low) c = (char)tolower((unsigned char)c);
    size_t at = low.find("motortown/content/");
    if (at == std::string::npos || low.size() < 7 || low.compare(low.size() - 7, 7, ".uasset") != 0) return "";
    if (t.size() - 7 <= at + 18) return "";
    std::string rest = t.substr(at + 18, t.size() - 7 - (at + 18));
    size_t sl = rest.rfind('/');
    return "/Game/" + rest + "." + (sl == std::string::npos ? rest : rest.substr(sl + 1));
}
// Primary index + (v10+) the full directory index -> every file's path. false + why on anything unexpected.
static bool parseIndex(uint32_t ver, const uint8_t* idx, size_t n, const std::function<bool(uint64_t, uint64_t, std::vector<uint8_t>&)>& readAt,
                       std::vector<std::string>& files, std::string& why) {
    Rd r{idx, n};
    std::string mount = r.fstr();
    int32_t count = r.get<int32_t>();
    if (r.bad || count < 0 || count > 20000000) { why = "bad index header"; return false; }
    if (ver < 10) {   // flat list: name + FPakEntry
        for (int32_t k = 0; k < count && !r.bad; k++) {
            std::string name = r.fstr();
            r.skip(24); uint32_t comp = r.get<uint32_t>(); r.skip(20);
            if (comp) { uint32_t b = r.get<uint32_t>(); if (b > 1000000) { why = "bad entry"; return false; } r.skip((size_t)b * 16); }
            r.skip(5);
            files.push_back(mount + name);
        }
        if (r.bad) { why = "index truncated"; files.clear(); return false; }
        return true;
    }
    r.get<uint64_t>();   // path hash seed
    if (r.get<int32_t>()) r.skip(8 + 8 + 20);
    uint64_t dOff = 0, dSize = 0;
    if (r.get<int32_t>()) { dOff = r.get<uint64_t>(); dSize = r.get<uint64_t>(); r.skip(20); }
    if (r.bad) { why = "index truncated"; return false; }
    if (!dSize) { why = "no full directory index"; return false; }
    std::vector<uint8_t> d;
    if (dSize > (1u << 28) || !readAt(dOff, dSize, d)) { why = "directory index unreadable"; return false; }
    Rd q{d.data(), d.size()};
    int32_t dirs = q.get<int32_t>();
    if (q.bad || dirs < 0 || dirs > 20000000) { why = "bad directory index"; return false; }
    for (int32_t a = 0; a < dirs && !q.bad; a++) {
        std::string dir = q.fstr();
        int32_t fc = q.get<int32_t>();
        if (fc < 0 || fc > 20000000) { q.bad = true; break; }
        for (int32_t b = 0; b < fc && !q.bad; b++) { std::string f = q.fstr(); q.get<int32_t>(); files.push_back(mount + dir + f); }
    }
    if (q.bad) { why = "directory index truncated (compressed or encrypted?)"; files.clear(); return false; }
    return true;
}
static bool readPak(const std::wstring& path, std::vector<std::string>& files, std::string& why) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) { why = "cannot open"; return false; }
    LARGE_INTEGER sz; GetFileSizeEx(h, &sz);
    auto readAt = [&](uint64_t off, uint64_t n, std::vector<uint8_t>& out) {
        if (off + n > (uint64_t)sz.QuadPart) return false;
        LARGE_INTEGER o; o.QuadPart = (LONGLONG)off; out.resize((size_t)n);
        DWORD got = 0;
        return SetFilePointerEx(h, o, nullptr, FILE_BEGIN) && ReadFile(h, out.data(), (DWORD)n, &got, nullptr) && got == n;
    };
    bool ok = false;
    std::vector<uint8_t> tail;
    uint64_t tn = (uint64_t)sz.QuadPart < 300 ? (uint64_t)sz.QuadPart : 300;
    if (!readAt(sz.QuadPart - tn, tn, tail)) why = "cannot read footer";
    else {
        int m = -1;
        for (int k = (int)tail.size() - 24; k >= 1; k--)
            if (tail[k] == 0xE1 && tail[k + 1] == 0x12 && tail[k + 2] == 0x6F && tail[k + 3] == 0x5A) { m = k; break; }
        if (m < 0) why = "no pak footer";
        else {
            uint32_t ver; uint64_t off, size;
            memcpy(&ver, &tail[m + 4], 4); memcpy(&off, &tail[m + 8], 8); memcpy(&size, &tail[m + 16], 8);
            if (tail[m - 1]) why = "encrypted index";
            else if (ver < 8 || ver > 11) why = "unsupported pak version " + std::to_string(ver);
            else {
                std::vector<uint8_t> idx;
                if (size > (1u << 29) || !readAt(off, size, idx)) why = "index unreadable";
                else ok = parseIndex(ver, idx.data(), idx.size(), readAt, files, why);
            }
        }
    }
    CloseHandle(h);
    return ok;
}
static std::string lowerStr(std::string s) { for (auto& c : s) c = (char)tolower((unsigned char)c); return s; }
static void findPaks(const std::wstring& dir, std::vector<std::pair<std::string, std::wstring>>& out) {
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        std::wstring n = fd.cFileName;
        if (n == L"." || n == L"..") continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) { findPaks(dir + L"\\" + n, out); continue; }
        if (n.size() < 4 || _wcsicmp(n.c_str() + n.size() - 4, L".pak") != 0) continue;
        std::string u8(WideCharToMultiByte(CP_UTF8, 0, n.c_str(), -1, nullptr, 0, nullptr, nullptr), 0);
        WideCharToMultiByte(CP_UTF8, 0, n.c_str(), -1, u8.data(), (int)u8.size(), nullptr, nullptr);
        u8.resize(strlen(u8.c_str()));
        std::string l = lowerStr(u8);   // the game's own and the framework's own are not mods
        if (l.rfind("motortown-windows", 0) == 0 || (l.size() > 18 && l.compare(l.size() - 18, 18, "-windowsserver.pak") == 0) ||
            l.rfind("aaaa_datatableframework", 0) == 0) continue;
        out.push_back({l, dir + L"\\" + n});
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}
static bool safeReadPak(const std::wstring& full, std::vector<std::string>& files, std::string& why) {
    __try { return readPak(full, files, why); } __except (EXCEPTION_EXECUTE_HANDLER) { why = "fault while parsing"; return false; }
}
// Paks the game's mod review switched off (CustomPak.ini [CustomPakStateV2] PakN.UserEnabled=False) are not mounted:
// their tables cannot load, so they are not candidates (11-25: a switched-off mod's tables failed to load).
static std::set<std::wstring> disabledPaks() {
    std::set<std::wstring> off;
    wchar_t la[MAX_PATH]; if (!GetEnvironmentVariableW(L"LOCALAPPDATA", la, MAX_PATH)) return off;
    FILE* f = _wfopen((std::wstring(la) + L"/MotorTown/Saved/Config/Windows/CustomPak.ini").c_str(), L"rb");
    if (!f) return off;
    std::string t; char buf[4096]; size_t k; while ((k = fread(buf, 1, sizeof buf, f)) > 0) t.append(buf, k); fclose(f);
    size_t sec = t.rfind("[CustomPakStateV2]"); if (sec == std::string::npos) return off;
    std::map<std::string, std::string> key, en;   // PakN -> stable key / UserEnabled
    size_t at = sec;
    while ((at = t.find('\n', at)) != std::string::npos) {
        size_t e = t.find('\n', ++at); std::string line = t.substr(at, (e == std::string::npos ? t.size() : e) - at);
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) line.pop_back();
        if (!line.empty() && line[0] == '[') break;
        size_t dot = line.find('.'), eq = line.find('=');
        if (dot == std::string::npos || eq == std::string::npos || dot > eq) continue;
        std::string id = line.substr(0, dot), field = line.substr(dot + 1, eq - dot - 1), val = line.substr(eq + 1);
        if (field == "StableKey") key[id] = val; else if (field == "UserEnabled") en[id] = val;
    }
    for (auto& [id, k2] : key)
        if (en.count(id) && _stricmp(en[id].c_str(), "False") == 0) {
            size_t sl = k2.find_last_of("/\\"); std::string base = sl == std::string::npos ? k2 : k2.substr(sl + 1);
            std::wstring w(base.begin(), base.end()); for (auto& c : w) c = (wchar_t)towlower(c); off.insert(w);
        }
    return off;
}
// Candidate table paths from every mod pak, in mount order (pak names sorted case-insensitively; a later pak wins).
static std::vector<std::string> discover() {
    std::set<std::wstring> off = disabledPaks();
    std::vector<std::pair<std::string, std::wstring>> paks;
    findPaks(gameDir() + L"..\\..\\Content\\Paks", paks);
    std::sort(paks.begin(), paks.end());
    std::vector<std::string> out; std::set<std::string> seen;
    for (auto& [nm, full] : paks) {
        {   std::wstring base = full.substr(full.find_last_of(L"\\/") + 1); for (auto& c : base) c = (wchar_t)towlower(c);
            if (off.count(base)) { MT_LOG("ZMT Loader: pak %s skipped: switched off in Mods [Review]", nm.c_str()); continue; } }
        std::vector<std::string> files; std::string why;
        if (!safeReadPak(full, files, why)) { MT_LOG("ZMT Loader: pak %s skipped: %s", nm.c_str(), why.c_str()); continue; }
        int n = 0;
        for (auto& f : files) {
            std::string g = gamePathOf(f);
            if (g.size() > 16 && _strnicmp(g.c_str(), "/Game/DataAsset/", 16) == 0 && seen.insert(g).second) { out.push_back(g); n++; }
        }
        if (n) MT_LOG("ZMT Loader: pak %s: %d candidate(s)", nm.c_str(), n);
    }
    return out;
}

// ===================================================================== engine access
static uintptr_t cDT, cComp, cLib, libCdo, fRowNames, onParents;
static int oParents = -1, oRowStruct = -1, pTable = -1, pOut = -1;
static bool dryRun = false, dedicated = false, canLoad = false;
static uintptr_t systemCDO, fPath, fRef, fLoad;
static int lPath = -1, lPathRet, lRefIn, lRefRet, lLoadIn, lLoadRet;

struct TArr { uintptr_t data; int32_t num, max; };

static std::string nameAt(uintptr_t o) { return fname(o + L().obj_name); }
static bool isPackage(uintptr_t o) { return o && outerOf(o) == 0; }
static std::string tableId(uintptr_t o) {
    uintptr_t pk = outerOf(o);
    return isPackage(pk) ? nameAt(pk) + "." + nameAt(o) : "";
}
static uintptr_t findTable(const std::string& id, bool comp) {
    size_t d = id.rfind('.');
    if (d == std::string::npos) return 0;
    return api->find_object(comp ? "CompositeDataTable" : "DataTable", id.substr(d + 1).c_str(), id.substr(0, d).c_str());
}
static std::string structId(uintptr_t st) {
    if (!st) return "";
    uintptr_t pk = outerOf(st);
    return nameAt(st) + "@" + (pk ? nameAt(pk) : "");
}

static bool resolve() {
    cDT = api->find_object("Class", "DataTable", "/Script/Engine");
    cComp = api->find_object("Class", "CompositeDataTable", "/Script/Engine");
    cLib = api->find_object("Class", "DataTableFunctionLibrary", "/Script/Engine");
    libCdo = api->find_object("DataTableFunctionLibrary", "Default__DataTableFunctionLibrary", "/Script/Engine");
    fRowNames = api->find_object("Function", "GetDataTableRowNames", "DataTableFunctionLibrary");
    uintptr_t cdo = api->find_object("CompositeDataTable", "Default__CompositeDataTable", "/Script/Engine");
    if (!cDT || !cComp || !cLib || !libCdo || !fRowNames || !cdo) { MT_LOG("ZMT Loader: engine class/function missing, doing nothing"); return false; }
    systemCDO = api->find_object("KismetSystemLibrary", "Default__KismetSystemLibrary", "/Script/Engine");
    fPath = api->find_object("Function", "MakeSoftObjectPath", "KismetSystemLibrary");
    fRef = api->find_object("Function", "Conv_SoftObjPathToSoftObjRef", "KismetSystemLibrary");
    fLoad = api->find_object("Function", "LoadAsset_Blocking", "KismetSystemLibrary");
    if (systemCDO && fPath && fRef && fLoad) {
        lPath = off(fPath, "PathString"); lPathRet = off(fPath, "ReturnValue"); lRefIn = off(fRef, "SoftObjectPath");
        lRefRet = off(fRef, "ReturnValue"); lLoadIn = off(fLoad, "Asset"); lLoadRet = off(fLoad, "ReturnValue");
        canLoad = lPath >= 0 && lPathRet >= 0 && lRefIn >= 0 && lRefRet > lRefIn && lLoadIn >= 0 && lLoadRet > lLoadIn && lLoadRet < 0x60 && lRefRet < 0x60;
    }
    if (!canLoad) MT_LOG("ZMT Loader: LoadAsset_Blocking path not available, mod tables nothing else loads stay unseen");
    oParents = off(cComp, "ParentTables");
    oRowStruct = off(cDT, "RowStruct");
    pTable = off(fRowNames, "Table");
    pOut = off(fRowNames, "OutRowNames");
    if (oParents < 0 || oRowStruct < 0 || pTable < 0 || pOut < 0 || pTable > 0x60 || pOut > 0x60) {
        MT_LOG("ZMT Loader: ParentTables/RowStruct/GetDataTableRowNames field not found, doing nothing"); return false;
    }
    // OnParentTablesUpdated: the call after `mov edx,1` in the composite's Serialize overrides (vtable slots 27 and 28).
    uintptr_t vt = get<uintptr_t>(cdo);
    auto base = (const uint8_t*)api->module_base();
    auto nt = (const IMAGE_NT_HEADERS64*)(base + ((const IMAGE_DOS_HEADER*)base)->e_lfanew);
    uintptr_t lo = (uintptr_t)base, hi = lo + nt->OptionalHeader.SizeOfImage;
    uintptr_t found[2] = {0, 0};
    for (int k = 0; k < 2; k++) {
        uintptr_t fn = vt ? get<uintptr_t>(vt + (28 - k) * 8) : 0;
        uint8_t b[200];
        if (fn < lo || fn >= hi || !rd(fn, b, sizeof b)) break;
        for (int i = 0; i + 5 <= (int)sizeof b && !found[k]; i++) {
            if (b[i] != 0xBA || b[i + 1] != 1 || b[i + 2] || b[i + 3] || b[i + 4]) continue;
            for (int j = i + 5; j <= i + 5 + 12 && j + 5 <= (int)sizeof b; j++) {
                if (b[j] != 0xE8) continue;
                int32_t rel; memcpy(&rel, b + j + 1, 4);
                found[k] = fn + j + 5 + rel;
                break;
            }
        }
    }
    if (!found[0] || found[0] != found[1] || found[0] < lo || found[0] >= hi) {
        MT_LOG("ZMT Loader: OnParentTablesUpdated not found (slot 28 -> %p, slot 27 -> %p), doing nothing", (void*)found[0], (void*)found[1]);
        return false;
    }
    onParents = found[0];
    MT_LOG("ZMT Loader: OnParentTablesUpdated at exe+0x%llx, ParentTables at +0x%x", (unsigned long long)(onParents - lo), oParents);
    return true;
}

static bool callOnParents(uintptr_t comp) {
    __try { ((void (*)(uintptr_t, int))onParents)(comp, 1); return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

// GetDataTableRowNames(table) through the engine: the returned array is engine-allocated memory (num = row count).
static bool rowNames(uintptr_t table, TArr& out) {
    alignas(16) unsigned char p[0x80] = {0};
    memcpy(p + pTable, &table, 8);
    api->process_event(libCdo, fRowNames, p);
    memcpy(&out, p + pOut, sizeof out);
    return out.data && out.num >= 0 && out.max >= out.num;
}

// What the scan thread found: ids -> live objects.
static std::unordered_map<std::string, uintptr_t> ptrOf;

static std::vector<std::string> scan(std::vector<PT>& tables) {
    std::unordered_map<uintptr_t, int> kind;   // class -> 0 none, 1 DataTable, 2 CompositeDataTable
    std::vector<std::string> framework;
    for (int i = 0, n = api->num_objects(); i < n; i++) {
        uintptr_t o = api->object(i);
        if (!o || (get<uint32_t>(o + L().obj_flags) & 0x30) || isCDO(o)) continue;
        uintptr_t cls = classOf(o);
        auto it = kind.find(cls);
        if (it == kind.end()) it = kind.emplace(cls, api->is_a(cls, cComp) ? 2 : api->is_a(cls, cDT) ? 1 : 0).first;
        if (!it->second) continue;
        std::string id = tableId(o);
        if (id.empty()) continue;
        PT t; t.name = id; t.comp = it->second == 2; t.mount = i;
        t.st = structId(get<uintptr_t>(o + oRowStruct));
        if (t.comp) {
            TArr a;
            if (rd(o + oParents, &a, sizeof a) && a.num > 0 && a.num < 100000) {
                std::vector<uintptr_t> ps(a.num);
                if (rd(a.data, ps.data(), 8 * (size_t)a.num))
                    for (uintptr_t p : ps) t.parents.push_back(p ? tableId(p) : "");
            }
            if (id.rfind("/Game/DataAsset/", 0) == 0) framework.push_back(id);
        }
        ptrOf[id] = o;
        tables.push_back(std::move(t));
    }
    return framework;
}

// ===================================================================== load candidates (game thread, small batches)
struct FStr { const wchar_t* data; int num, max; };
static uintptr_t loadOne(const wchar_t* path) {   // suspension_tuning's loadAsset, minus the rooting: only tables are kept
    unsigned char a[0x80] = {0}, b[0x80] = {0}, c[0x80] = {0};
    int n = (int)wcslen(path) + 1;
    FStr s = {path, n, n};
    uintptr_t out = 0;
    __try {
        memcpy(a + lPath, &s, sizeof s);
        api->process_event(systemCDO, fPath, a);
        memcpy(b + lRefIn, a + lPathRet, lRefRet - lRefIn);
        api->process_event(systemCDO, fRef, b);
        memcpy(c + lLoadIn, b + lRefRet, lLoadRet - lLoadIn);
        api->process_event(systemCDO, fLoad, c);
        memcpy(&out, c + lLoadRet, 8);
    } __except (EXCEPTION_EXECUTE_HANDLER) { out = 0; }
    return out;
}
struct GJ { std::function<void()> f; HANDLE ev; };
// Runs f on the game thread and waits. On a timeout the job still owns its memory (it frees itself).
static bool onGame(std::function<void()> f, DWORD timeout = 120000) {
    GJ* j = new GJ{std::move(f), CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    HANDLE ev = j->ev;
    if (!api->run_on_game_thread([](void* c) { GJ* j = (GJ*)c; HANDLE e = j->ev; j->f(); delete j; SetEvent(e); }, j)) { CloseHandle(ev); delete j; return false; }
    bool ok = WaitForSingleObject(ev, timeout) == WAIT_OBJECT_0;
    if (ok) CloseHandle(ev);
    return ok;
}
static void loadCandidates(const std::vector<std::string>& cands) {
    LARGE_INTEGER hz, a, b; QueryPerformanceFrequency(&hz); QueryPerformanceCounter(&a);
    std::vector<std::wstring> todo;
    for (auto& c : cands) {   // "/Game/X/Y.Y" already loaded (as a table or a composite): nothing to do
        if (findTable(c, false) || findTable(c, true)) continue;
        std::wstring w(MultiByteToWideChar(CP_UTF8, 0, c.c_str(), -1, nullptr, 0), 0);
        MultiByteToWideChar(CP_UTF8, 0, c.c_str(), -1, w.data(), (int)w.size());
        w.resize(wcslen(w.c_str()));
        todo.push_back(w);
    }
    int loaded = 0, tables = 0;
    if (dryRun && !todo.empty()) MT_LOG("ZMT Loader: dry run: loading the candidate tables anyway (the plan needs them)");
    for (size_t at = 0; canLoad && at < todo.size() && !api->stopping(); at += 20) {
        size_t end = (std::min)(todo.size(), at + 20);
        if (!onGame([&] {
                for (size_t i = at; i < end; i++) {
                    uintptr_t o = loadOne(todo[i].c_str());
                    static int toldFail, toldOk;
                    if (!o) {
                        if (toldFail++ < 15) MT_LOG("ZMT Loader: load failed: %ls", todo[i].c_str());
                        continue;
                    }
                    loaded++;
                    uintptr_t cls = classOf(o);
                    if (toldOk++ < 15) MT_LOG("ZMT Loader: loaded %ls -> %s (%s)", todo[i].c_str(), objName(o).c_str(), objName(cls).c_str());
                    if (api->is_a(cls, cDT) && !api->is_a(cls, cComp)) { rooted(o); tables++; }
                }
            })) { MT_LOG("ZMT Loader: game thread did not run a load batch, stopping the loads"); break; }
        Sleep(50);   // a frame or two between batches
    }
    QueryPerformanceCounter(&b);
    MT_LOG("ZMT Loader: candidates %zu, to load %zu, loaded %d, data tables %d, %.0f ms", cands.size(), todo.size(), loaded, tables,
           (b.QuadPart - a.QuadPart) * 1000.0 / hz.QuadPart);
}

// ===================================================================== apply (game thread)
struct Result {
    PC pc;
    long rowsBefore = -1, rowsAfter = -1;
    bool done = false, applied = false;
};
struct Job {
    std::vector<PC>* plan;
    std::map<std::string, Result>* results;
    HANDLE ev;
    int pending = 0;
    double gameMs;  // how long the apply took on the game thread
};

static void applyOne(const PC& pc, Result& r) {
    r.pc = pc;
    if (pc.added.empty()) { r.pc.after = pc.before; r.done = true; return; }
    uintptr_t comp = ptrOf[pc.name];
    std::vector<uintptr_t> add;
    for (auto& n : pc.added) { uintptr_t t = ptrOf[n]; if (!t) { r.pc.skipped.push_back({n, "table object gone"}); continue; } add.push_back(t); }
    TArr old;
    if (!comp || !rd(comp + oParents, &old, sizeof old) || old.num < 0 || old.num > 100000) { r.pc.skipped.push_back({pc.name, "ParentTables unreadable"}); r.done = true; return; }
    TArr buf;
    if (!rowNames(comp, buf)) { r.pc.skipped.push_back({pc.name, "GetDataTableRowNames failed"}); r.done = true; return; }
    r.rowsBefore = buf.num;
    if (buf.num == 0) return;   // not loaded yet: retry
    r.done = true;
    r.pc.added.clear();
    for (auto n : pc.added) if (ptrOf[n]) r.pc.added.push_back(n);
    r.pc.after = pc.before; r.pc.after.insert(r.pc.after.end(), r.pc.added.begin(), r.pc.added.end());
    if (dryRun) { r.rowsAfter = r.rowsBefore; return; }
    long N = old.num + (long)add.size();
    if (N > buf.max) { r.pc.skipped.push_back({pc.name, "engine buffer too small"}); r.pc.added.clear(); r.pc.after = pc.before; return; }
    std::vector<uintptr_t> ps(N);
    if (old.num && !rd(old.data, ps.data(), 8 * (size_t)old.num)) { r.pc.skipped.push_back({pc.name, "ParentTables unreadable"}); r.pc.added.clear(); r.pc.after = pc.before; return; }
    for (size_t i = 0; i < add.size(); i++) ps[old.num + i] = add[i];
    TArr neu = {buf.data, (int32_t)N, buf.max};
    if (!wr(buf.data, ps.data(), 8 * (size_t)N) || !wr(comp + oParents, &neu, sizeof neu)) { r.pc.skipped.push_back({pc.name, "write failed"}); return; }
    bool ok = callOnParents(comp);
    TArr after;
    long rows = ok && rowNames(comp, after) ? after.num : -1;
    if (rows < r.rowsBefore) {   // rebuild lost rows or faulted: put the old parents back
        wr(comp + oParents, &old, sizeof old);
        callOnParents(comp);
        r.pc.skipped.push_back({pc.name, "reverted: rows " + std::to_string(r.rowsBefore) + " -> " + std::to_string(rows)});
        r.pc.added.clear(); r.pc.after = pc.before; r.rowsAfter = r.rowsBefore;
        MT_LOG("ZMT Loader: %s reverted (rows %ld -> %ld)", pc.name.c_str(), r.rowsBefore, rows);
        return;
    }
    r.rowsAfter = rows; r.applied = true;
    MT_LOG("ZMT Loader: %s +%d tables, rows %ld -> %ld", pc.name.c_str(), (int)r.pc.added.size(), r.rowsBefore, rows);
}

static void gameJob(void* ctx) {
    Job* j = (Job*)ctx;
    LARGE_INTEGER hz, a, b; QueryPerformanceFrequency(&hz); QueryPerformanceCounter(&a);
    for (auto& pc : *j->plan) {
        Result& r = (*j->results)[pc.name];
        if (r.done) continue;
        applyOne(pc, r);
        if (!r.done) j->pending++;
    }
    QueryPerformanceCounter(&b); j->gameMs = (b.QuadPart - a.QuadPart) * 1000.0 / hz.QuadPart;
    SetEvent(j->ev);
}

// ===================================================================== files
static std::wstring logsDir() { return gameDir() + L"plugins\\logs\\ZMTLoader\\"; }
static std::string readFile(const std::wstring& p) {
    std::string s;
    HANDLE h = CreateFileW(p.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return s;
    char b[4096]; DWORD n;
    while (ReadFile(h, b, sizeof b, &n, nullptr) && n) s.append(b, n);
    CloseHandle(h);
    return s;
}
static void writeFile(const std::wstring& p, const std::string& s) {
    HANDLE h = CreateFileW(p.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD n; WriteFile(h, s.data(), (DWORD)s.size(), &n, nullptr);
    CloseHandle(h);
}
static std::wstring cachePath() { return gameDir() + L"plugins\\zmt_loader_cache.json"; }

static void writeCache(const std::string& sha, const std::vector<std::string>& cands, const std::map<std::string, Result>& res) {
    std::string o = "{\"version\":\"" + std::string(CACHE_VERSION) + "\",\"sha\":" + esc(sha) + ",\"candidates\":" + strList(cands) + ",\"plan\":{";
    bool first = true;
    for (auto& [n, r] : res) { o += (first ? "" : ",") + esc(n) + ":" + strList(r.pc.added); first = false; }
    writeFile(cachePath(), o + "}}\n");
}
static bool readCachedCandidates(const std::string& sha, std::vector<std::string>& cands) {
    std::string s = readFile(cachePath());
    size_t i = 0; J root;
    if (s.empty() || !parseJ(s, i, root) || root.t != 'o') return false;
    std::string ver, got; const J* cl = nullptr;
    for (auto& [k, v] : root.o) { if (k == "version") ver = v.s; else if (k == "sha") got = v.s; else if (k == "candidates") cl = &v; }
    if (ver != CACHE_VERSION || got != sha || !cl || cl->t != 'a') return false;
    for (auto& e : cl->a) cands.push_back(e.s);
    return true;
}
static bool readCache(const std::string& sha, std::vector<PC>& plan) {
    std::string s = readFile(cachePath());
    size_t i = 0; J root;
    if (s.empty() || !parseJ(s, i, root) || root.t != 'o') return false;
    std::string ver, got; const J* pl = nullptr;
    for (auto& [k, v] : root.o) { if (k == "version") ver = v.s; else if (k == "sha") got = v.s; else if (k == "plan") pl = &v; }
    if (ver != CACHE_VERSION || got != sha || !pl || pl->t != 'o') return false;
    for (auto& [k, v] : pl->o) {
        PC pc; pc.name = k;
        uintptr_t c = findTable(k, true);
        if (!c || v.t != 'a') return false;
        TArr a;
        if (!rd(c + oParents, &a, sizeof a) || a.num < 0 || a.num > 100000) return false;
        std::vector<uintptr_t> ps(a.num);
        if (a.num && !rd(a.data, ps.data(), 8 * (size_t)a.num)) return false;
        for (uintptr_t p : ps) pc.before.push_back(p ? tableId(p) : "");
        ptrOf[k] = c;
        for (auto& e : v.a) {
            uintptr_t t = findTable(e.s, false);
            if (!t) return false;   // a table the plan names is not loaded: rescan
            ptrOf[e.s] = t; pc.added.push_back(e.s);
        }
        plan.push_back(pc);
    }
    return !plan.empty();
}

static void writePlan(const std::string& sha, bool hit, const std::map<std::string, Result>& res) {
    CreateDirectoryW((gameDir() + L"plugins\\logs").c_str(), nullptr);
    CreateDirectoryW(logsDir().c_str(), nullptr);
    std::string o = "{\n \"sha\": " + esc(sha) + ",\n \"dry_run\": " + (dryRun ? "true" : "false") +
                    ",\n \"cache_hit\": " + (hit ? "true" : "false") + ",\n \"composites\": {\n";
    bool first = true;
    for (auto& [n, r] : res) {
        const PC& p = r.pc;
        o += std::string(first ? "" : ",\n") + "  " + esc(n) + ": {\"struct\": " + esc(p.st) + ", \"before\": " + strList(p.before) +
             ", \"after\": " + strList(p.after) + ", \"added\": " + strList(p.added) + ", \"skipped\": [";
        for (size_t i = 0; i < p.skipped.size(); i++)
            o += std::string(i ? ", " : "") + "{\"table\": " + esc(p.skipped[i].table) + ", \"reason\": " + esc(p.skipped[i].reason) + "}";
        o += "], \"rows_before\": " + std::to_string(r.rowsBefore) + ", \"rows_after\": " + std::to_string(r.rowsAfter) + "}";
        first = false;
    }
    writeFile(logsDir() + L"plan_" + std::wstring(sha.begin(), sha.end()) + L".json", o + "\n }\n}\n");
}

// ===================================================================== thread
static DWORD WINAPI run(LPVOID) {
    if (!api->wait_engine(600000) || !resolve()) return 0;
    while (!api->game_thread_ready()) { if (api->stopping()) return 0; Sleep(2000); }
    if (dedicated) {
        // A server has no PlayerController: a GameState and framework composites that have rows, then 10 s more.
        uintptr_t cGS = api->find_object("Class", "GameStateBase", "/Script/Engine");
        if (!cGS) { MT_LOG("ZMT Loader: no GameStateBase class -- scanning after a delay"); Sleep(30000); }
        for (int waited = 0; cGS; waited += 3) {
            if (api->stopping()) return 0;
            bool gs = false;
            for (int i = 0, n = api->num_objects(); i < n && !gs; i++) {
                uintptr_t o = api->object(i);
                if (o && !isCDO(o) && api->is_a(classOf(o), cGS)) gs = true;
            }
            bool rows = false;
            if (gs) {
                std::vector<PT> t; ptrOf.clear();
                std::vector<std::string> fw = scan(t);
                std::vector<uintptr_t> comps;
                for (auto& n : fw) comps.push_back(ptrOf[n]);
                bool all = !comps.empty();
                if (all && !onGame([&] { for (uintptr_t c : comps) { TArr b; if (!rowNames(c, b) || b.num <= 0) { all = false; break; } } })) return 0;
                rows = all;
            }
            if (rows) break;
            if (waited >= 600) { MT_LOG("ZMT Loader: dedicated server: framework composites still without rows after 10 min, going on"); break; }
            Sleep(3000);
        }
        Sleep(10000);
        MT_LOG("ZMT Loader: dedicated server ready, scanning");
    } else {
    // Wait for a world with a player in it: at the main menu only some composites and mod tables are loaded
    // (11-25 dry run: 8 of 14 composites, scanned 40 s before the world). Then 10 s more for the world's own loads.
    {
        uintptr_t cPC = api->find_object("Class", "PlayerController", "/Script/Engine");
        uintptr_t cCtl = api->find_object("Class", "Controller", "/Script/Engine");
        int oPawn = cCtl ? off(cCtl, "Pawn") : -1;
        bool inWorld = false;
        for (int waited = 0; !inWorld && cPC && oPawn >= 0; waited += 3) {
            if (api->stopping()) return 0;
            for (int i = 0, n = api->num_objects(); i < n && !inWorld; i++) {
                uintptr_t o = api->object(i);
                if (o && !isCDO(o) && api->is_a(classOf(o), cPC) && get<uintptr_t>(o + oPawn)) inWorld = true;
            }
            if (!inWorld) Sleep(3000);
            if (waited == 600) MT_LOG("ZMT Loader: still waiting for a world (10 min)");
        }
        if (!cPC || oPawn < 0) MT_LOG("ZMT Loader: no PlayerController/Pawn to wait for -- scanning after a delay");
        Sleep(10000);
        MT_LOG("ZMT Loader: in a world, scanning");
    }
    }
    // timings for the log (the user, 11-25: "how much time does it take?")
    LARGE_INTEGER hz, t0, t1; QueryPerformanceFrequency(&hz);
    auto ms = [&](LARGE_INTEGER a, LARGE_INTEGER b) { return (b.QuadPart - a.QuadPart) * 1000.0 / hz.QuadPart; };
    QueryPerformanceCounter(&t0);
    std::string sha = fingerprint();
    QueryPerformanceCounter(&t1); MT_LOG("ZMT Loader: fingerprint %.1f ms", ms(t0, t1));
    if (sha.empty()) { MT_LOG("ZMT Loader: fingerprint failed, doing nothing"); return 0; }
    std::vector<std::string> cands;
    if (readCachedCandidates(sha, cands)) MT_LOG("ZMT Loader: %zu candidate path(s) from the cache", cands.size());
    else {
        QueryPerformanceCounter(&t0);
        cands = discover();
        QueryPerformanceCounter(&t1); MT_LOG("ZMT Loader: pak indexes read, %zu candidate path(s), %.1f ms", cands.size(), ms(t0, t1));
    }
    loadCandidates(cands);
    std::map<std::string, Result> results;
    bool hit = false, tryCache = true;
    for (int attempt = 0; attempt < 12; attempt++) {
        if (api->stopping()) return 0;
        std::vector<PC> plan;
        ptrOf.clear();
        if (tryCache && readCache(sha, plan)) { hit = true; MT_LOG("ZMT Loader: cache hit %s", sha.c_str()); }
        else {
            hit = false;
            std::vector<PT> tables;
            QueryPerformanceCounter(&t0);
            std::vector<std::string> fw = scan(tables);
            plan = planTables(tables, fw);
            QueryPerformanceCounter(&t1); MT_LOG("ZMT Loader: scan + plan %.1f ms (plugin thread, %zu tables)", ms(t0, t1), tables.size());
        }
        tryCache = false;
        Job job = {&plan, &results, CreateEventW(nullptr, TRUE, FALSE, nullptr), 0, 0};
        if (plan.empty() || !api->run_on_game_thread(gameJob, &job)) { CloseHandle(job.ev); job.pending = 1; }
        else {
            bool ok = WaitForSingleObject(job.ev, 120000) == WAIT_OBJECT_0;
            CloseHandle(job.ev);
            if (!ok) { MT_LOG("ZMT Loader: game thread did not run the job, stopping"); return 0; }
            MT_LOG("ZMT Loader: apply %.1f ms on the game thread", job.gameMs);
        }
        if (job.pending == 0) break;
        MT_LOG("ZMT Loader: attempt %d: %d composites not ready, retrying", attempt + 1, job.pending);
        Sleep(10000);
    }
    writePlan(sha, hit, results);
    int n = 0; for (auto& [k, r] : results) n += (int)r.pc.added.size();
    writeCache(sha, cands, results);
    MT_LOG("ZMT Loader: %d composites, %d tables %s (plan_%s.json)", (int)results.size(), n, dryRun ? "planned (dry run)" : "added", sha.c_str());
    return 0;
}

extern "C" __declspec(dllexport) int PluginInit(const MtApi* a) {
    if (!attach(a)) return 1;
    if (iniDisabled(INI)) return 0;
    { wchar_t exe[MAX_PATH] = {}; GetModuleFileNameW(nullptr, exe, MAX_PATH); dedicated = wcsstr(exe, L"MotorTownServer") != nullptr; }
    dryRun = iniInt(INI, L"AutoPatch", L"DryRun", 0) != 0;
    CloseHandle(CreateThread(nullptr, 0, run, nullptr, 0, nullptr));
    return 0;
}
