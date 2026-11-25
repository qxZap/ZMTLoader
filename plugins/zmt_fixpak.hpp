// ZMT Loader fix pak: a composite data table asset and a pak, written without the editor or any tool.
// Pure (no engine access), so tools\zmt_fixpak_test.cpp builds it too.
//
// The composite is the layout the DataTable Framework's own composites use (cooked, unversioned, legacy file version
// -8, read with UAssetGUI as VER_UE5_4): a summary, the name map (with both name hashes), 32-byte imports, one 96-byte
// export, an empty depends map, an empty asset registry block and the preload dependencies. Its export holds the same
// three properties as the framework's (ParentTables, RowStruct and the string after them, copied) and no rows of its
// own: the game rebuilds a composite's rows from its parents when it loads (the framework's Decals composite and its
// hubs ship that way). The pak is version 8 (FNameBasedCompression, 5 name slots), uncompressed, like repak's default.
#pragma once
#include <windows.h>
#include <bcrypt.h>
#include <cstdint>
#include <cstring>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>
#pragma comment(lib, "bcrypt.lib")

namespace fixpak {
using Bytes = std::vector<uint8_t>;
static const uint32_t TAG = 0x9E2A83C1, PAK_MAGIC = 0x5A6F12E1;

// ---------------------------------------------------------------- hashes
static void hashBytes(const wchar_t* alg, const void* p, size_t n, uint8_t* out, ULONG outLen) {
    BCRYPT_ALG_HANDLE h = nullptr;
    memset(out, 0, outLen);
    if (BCryptOpenAlgorithmProvider(&h, alg, nullptr, 0) != 0) return;
    BCryptHash(h, nullptr, 0, (PUCHAR)p, (ULONG)n, out, outLen);
    BCryptCloseAlgorithmProvider(h, 0);
}
// The name map's two 16-bit hashes: FCrc::Strihash_DEPRECATED (one byte per ANSI char, upper-cased, the 0x04C11DB7
// table) and FCrc::StrCrc32 (four bytes per char, the reflected table). Checked against all 86 names of a cooked file.
static uint32_t nameHashes(const std::string& s) {
    static uint32_t td[256], ts[256];
    static bool init = false;
    if (!init) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i << 24;
            for (int k = 0; k < 8; k++) c = (c & 0x80000000u) ? (c << 1) ^ 0x04C11DB7u : c << 1;
            td[i] = c;
            c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? (c >> 1) ^ 0xEDB88320u : c >> 1;
            ts[i] = c;
        }
        init = true;
    }
    uint32_t a = 0, b = 0xFFFFFFFFu;
    for (unsigned char ch : s) {
        unsigned char up = (ch >= 'a' && ch <= 'z') ? (unsigned char)(ch - 32) : ch;
        a = ((a >> 8) & 0x00FFFFFFu) ^ td[(a ^ up) & 0xFF];
        uint32_t o = ch;
        for (int k = 0; k < 4; k++) { b = (b >> 8) ^ ts[(b ^ o) & 0xFF]; o >>= 8; }
    }
    b = ~b;
    return (a & 0xFFFF) | ((b & 0xFFFF) << 16);
}

// "Foo_12" is FName ("Foo", 13): only the base goes in the name map. "Foo_01" (leading zero) stays whole.
static std::pair<std::string, int32_t> splitName(const std::string& s) {
    size_t u = s.rfind('_');
    if (u == std::string::npos || u == 0 || u + 1 >= s.size() || u + 1 + 9 < s.size()) return {s, 0};
    if (s[u + 1] == '0' && u + 2 != s.size()) return {s, 0};
    for (size_t i = u + 1; i < s.size(); i++) if (s[i] < '0' || s[i] > '9') return {s, 0};
    return {s.substr(0, u), atoi(s.c_str() + u + 1) + 1};
}

// ---------------------------------------------------------------- byte reader / writer
struct In {
    const Bytes& b; size_t i = 0; bool bad = false;
    explicit In(const Bytes& x, size_t at = 0) : b(x), i(at) {}
    template <class T> T get() { T v{}; if (i + sizeof(T) > b.size()) { bad = true; return v; } memcpy(&v, b.data() + i, sizeof(T)); i += sizeof(T); return v; }
    std::string fstr() {
        int32_t n = get<int32_t>();
        if (bad || n == 0) return "";
        if (n < 0 || (size_t)n > b.size() - i) { bad = true; return ""; }   // wide strings never occur in these files
        std::string s((const char*)b.data() + i, n - 1); i += n; return s;
    }
};
struct Out {
    Bytes b;
    template <class T> void put(T v) { size_t k = b.size(); b.resize(k + sizeof(T)); memcpy(b.data() + k, &v, sizeof(T)); }
    void raw(const void* p, size_t n) { b.insert(b.end(), (const uint8_t*)p, (const uint8_t*)p + n); }
    void fstr(const std::string& s) { if (s.empty()) { put<int32_t>(0); return; } put<int32_t>((int32_t)s.size() + 1); raw(s.data(), s.size()); put<uint8_t>(0); }
    template <class T> void at(size_t k, T v) { memcpy(b.data() + k, &v, sizeof(T)); }
};

// ---------------------------------------------------------------- composite
struct Table { std::string pkg, name, cls; };   // a parent: "/Game/A/B", "B", "DataTable"
struct Composite {
    std::string pkg, name;                       // "/Game/DataAsset/Items/Items", "Items"
    std::string structPkg, structName;           // "/Script/MotorTown", "MTItemRow"
    std::vector<Table> parents;
    Bytes tail;                                  // the export's bytes after RowStruct, up to the row count
    uint32_t objectFlags = 0xB, packageFlags = 0x80042200, packageSource = 0;
    std::string id() const { return pkg + "." + name; }
};
static const uint16_t FRAGS[3] = {0x0200, 0x0201, 0x0304};

// A cooked composite (.uasset + .uexp) -> its parents, row struct and the bits a copy needs. false + why otherwise.
static bool parseComposite(const Bytes& ua, const Bytes& ue, Composite& c, std::string& why) {
    In r(ua);
    if (r.get<uint32_t>() != TAG || r.get<int32_t>() != -8) { why = "not a cooked package of the expected version"; return false; }
    r.get<int32_t>(); r.get<int32_t>(); r.get<int32_t>(); r.get<int32_t>();
    if (r.get<int32_t>() != 0) { why = "versioned package"; return false; }
    int32_t total = r.get<int32_t>();
    c.pkg = r.fstr();
    c.packageFlags = r.get<uint32_t>();
    int32_t nNames = r.get<int32_t>(), oNames = r.get<int32_t>();
    r.get<int32_t>(); r.get<int32_t>();                       // soft object paths
    if (!(c.packageFlags & 0x80000000u)) { why = "not filtered for editor-only data"; return false; }
    r.get<int32_t>(); r.get<int32_t>();                       // gatherable text
    int32_t nExp = r.get<int32_t>(), oExp = r.get<int32_t>(), nImp = r.get<int32_t>(), oImp = r.get<int32_t>(), oDep = r.get<int32_t>();
    r.i += 4 * 4 + 16;                                        // soft package refs, searchable names, thumbnails, guid
    int32_t gens = r.get<int32_t>(); if (gens < 0 || gens > 1000) { why = "bad generations"; return false; }
    r.i += 8 * (size_t)gens;
    for (int k = 0; k < 2; k++) { r.i += 10; r.fstr(); }      // engine versions
    r.get<uint32_t>();
    if (r.get<int32_t>() != 0) { why = "compressed chunks"; return false; }
    c.packageSource = r.get<uint32_t>();
    int32_t add = r.get<int32_t>(); for (int k = 0; k < add && !r.bad; k++) r.fstr();
    r.get<int32_t>(); r.get<int64_t>(); r.get<int32_t>();     // asset registry, bulk data, world tile
    int32_t chunks = r.get<int32_t>(); r.i += 4 * (size_t)(chunks < 0 ? 0 : chunks);
    r.get<int32_t>(); r.get<int32_t>(); r.get<int32_t>(); r.get<int64_t>(); r.get<int32_t>();
    if (r.bad || (int32_t)r.i != oNames) { why = "unknown summary layout"; return false; }
    std::vector<std::string> names;
    for (int k = 0; k < nNames && !r.bad; k++) { names.push_back(r.fstr()); r.get<uint32_t>(); }
    if (r.bad || nExp != 1 || oExp - oImp != 32 * nImp || oDep - oExp != 96) { why = "unexpected table layout"; return false; }
    auto fn = [&](In& q) -> std::string {
        int32_t a = q.get<int32_t>(), n = q.get<int32_t>();
        if (a < 0 || a >= (int32_t)names.size()) { q.bad = true; return ""; }
        return n ? names[a] + "_" + std::to_string(n - 1) : names[a];
    };
    struct Imp { std::string cpkg, cls, name; int32_t outer; };
    std::vector<Imp> imps;
    In q(ua, oImp);
    for (int k = 0; k < nImp; k++) { Imp m; m.cpkg = fn(q); m.cls = fn(q); m.outer = q.get<int32_t>(); m.name = fn(q); q.get<int32_t>(); imps.push_back(m); }
    auto imp = [&](int32_t idx) -> const Imp* { return idx < 0 && -idx - 1 < (int32_t)imps.size() ? &imps[-idx - 1] : nullptr; };
    In e(ua, oExp);
    const Imp* cls = imp(e.get<int32_t>());
    e.get<int32_t>(); e.get<int32_t>(); e.get<int32_t>();
    c.name = fn(e);
    c.objectFlags = e.get<uint32_t>();
    int64_t size = e.get<int64_t>(), off = e.get<int64_t>();
    if (q.bad || e.bad || !cls || cls->name != "CompositeDataTable" || off != total || (int64_t)ue.size() != size + 4) { why = "not a composite data table"; return false; }
    In x(ue);
    for (uint16_t f : FRAGS) if (x.get<uint16_t>() != f) { why = "unexpected property set"; return false; }
    int32_t np = x.get<int32_t>();
    if (np < 0 || np > 100000) { why = "bad parent count"; return false; }
    c.parents.clear();
    for (int k = 0; k < np; k++) {
        const Imp* o = imp(x.get<int32_t>());
        const Imp* p = o ? imp(o->outer) : nullptr;
        if (!o || !p) { why = "parent is not an import"; return false; }
        c.parents.push_back({p->name, o->name, o->cls});
    }
    const Imp* st = imp(x.get<int32_t>());
    const Imp* sp = st ? imp(st->outer) : nullptr;
    if (!st || !sp) { why = "row struct is not an import"; return false; }
    c.structName = st->name; c.structPkg = sp->name;
    size_t t0 = x.i; x.fstr(); x.get<int32_t>();
    if (x.bad) { why = "export truncated"; return false; }
    c.tail.assign(ue.begin() + t0, ue.begin() + x.i);
    return true;
}

// The copy: `c.parents` as ParentTables, no rows. Deterministic (the package guid comes from its path).
static void buildComposite(const Composite& c, Bytes& ua, Bytes& ue) {
    std::vector<std::string> names; std::map<std::string, int32_t> at;
    auto nm = [&](const std::string& s) { auto sp = splitName(s); if (!at.count(sp.first)) { at[sp.first] = (int32_t)names.size(); names.push_back(sp.first); } };
    struct Imp { std::string cpkg, cls, name; int32_t outer; };
    std::vector<Imp> imps; std::map<std::string, int32_t> pkgAt;
    auto add = [&](const std::string& cpkg, const std::string& cls, int32_t outer, const std::string& name) {
        imps.push_back({cpkg, cls, name, outer}); nm(cpkg); nm(cls); nm(name); return -(int32_t)imps.size(); };
    auto pkg = [&](const std::string& p) { auto f = pkgAt.find(p); if (f != pkgAt.end()) return f->second; return pkgAt[p] = add("/Script/CoreUObject", "Package", 0, p); };
    nm(c.name);
    int32_t iClass = add("/Script/CoreUObject", "Class", 0, "CompositeDataTable");
    int32_t iCdo = add("/Script/Engine", "CompositeDataTable", 0, "Default__CompositeDataTable");
    int32_t iEngine = pkg("/Script/Engine");
    imps[-iClass - 1].outer = iEngine; imps[-iCdo - 1].outer = iEngine;
    int32_t iStruct = add("/Script/CoreUObject", "ScriptStruct", pkg(c.structPkg), c.structName);
    std::vector<int32_t> par; std::set<std::string> seen;
    for (auto& t : c.parents) {
        if (!seen.insert(t.pkg + "." + t.name).second) continue;
        int32_t p = pkg(t.pkg);
        par.push_back(add("/Script/Engine", t.cls.empty() ? "DataTable" : t.cls, p, t.name));
    }
    // export data
    Out x;
    for (uint16_t f : FRAGS) x.put(f);
    x.put<int32_t>((int32_t)par.size());
    for (int32_t p : par) x.put(p);
    x.put(iStruct);
    x.raw(c.tail.data(), c.tail.size());
    x.put<int32_t>(0);                       // no rows of its own
    int64_t serial = (int64_t)x.b.size();
    x.put(TAG);
    ue = x.b;
    // header
    auto fname = [&](Out& o, const std::string& s) { auto sp = splitName(s); o.put<int32_t>(at[sp.first]); o.put<int32_t>(sp.second); };
    std::vector<int32_t> pre; pre.push_back(iStruct); pre.insert(pre.end(), par.begin(), par.end());
    size_t nSbs = pre.size(); pre.push_back(iClass); pre.push_back(iCdo);
    uint8_t guid[32]; hashBytes(BCRYPT_SHA256_ALGORITHM, c.pkg.data(), c.pkg.size(), guid, 32);
    Out h;
    h.put(TAG); h.put<int32_t>(-8); h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0);
    size_t pTotal = h.b.size(); h.put<int32_t>(0);
    h.fstr(c.pkg);
    h.put(c.packageFlags);
    h.put<int32_t>((int32_t)names.size()); size_t pNames = h.b.size(); h.put<int32_t>(0);
    h.put<int32_t>(0); size_t pSoft = h.b.size(); h.put<int32_t>(0);
    h.put<int32_t>(0); h.put<int32_t>(0);                                   // gatherable text
    h.put<int32_t>(1); size_t pExp = h.b.size(); h.put<int32_t>(0);
    h.put<int32_t>((int32_t)imps.size()); size_t pImp = h.b.size(); h.put<int32_t>(0);
    size_t pDep = h.b.size(); h.put<int32_t>(0);
    h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0);  // soft package refs, searchable, thumbnails
    h.raw(guid, 16);
    h.put<int32_t>(1); h.put<int32_t>(1); h.put<int32_t>((int32_t)names.size());
    for (int k = 0; k < 2; k++) { h.put<uint16_t>(0); h.put<uint16_t>(0); h.put<uint16_t>(0); h.put<uint32_t>(0); h.put<int32_t>(0); }
    h.put<uint32_t>(0); h.put<int32_t>(0); h.put(c.packageSource); h.put<int32_t>(0);
    size_t pAr = h.b.size(); h.put<int32_t>(0);
    size_t pBulk = h.b.size(); h.put<int64_t>(0);
    h.put<int32_t>(0); h.put<int32_t>(0);                                   // world tile, chunk ids
    h.put<int32_t>((int32_t)pre.size()); size_t pPre = h.b.size(); h.put<int32_t>(0);
    h.put<int32_t>((int32_t)names.size()); h.put<int64_t>(-1); h.put<int32_t>(-1);
    h.at<int32_t>(pNames, (int32_t)h.b.size());
    for (auto& s : names) { h.fstr(s); h.put(nameHashes(s)); }
    h.at<int32_t>(pSoft, (int32_t)h.b.size()); h.at<int32_t>(pImp, (int32_t)h.b.size());
    for (auto& m : imps) { fname(h, m.cpkg); fname(h, m.cls); h.put(m.outer); fname(h, m.name); h.put<int32_t>(0); }
    h.at<int32_t>(pExp, (int32_t)h.b.size());
    h.put(iClass); h.put<int32_t>(0); h.put(iCdo); h.put<int32_t>(0);
    fname(h, c.name);
    h.put(c.objectFlags);
    h.put(serial); size_t pOff = h.b.size(); h.put<int64_t>(0);
    h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0); h.put<int32_t>(0); h.put<uint32_t>(0);
    h.put<int32_t>(1); h.put<int32_t>(1); h.put<int32_t>(0);              // not always loaded for editor game, is asset, public hash
    h.put<int32_t>(0); h.put<int32_t>((int32_t)nSbs); h.put<int32_t>(0); h.put<int32_t>(2); h.put<int32_t>(0);
    h.at<int32_t>(pDep, (int32_t)h.b.size()); h.put<int32_t>(0);
    h.at<int32_t>(pAr, (int32_t)h.b.size()); h.put<int32_t>(0);
    h.at<int32_t>(pPre, (int32_t)h.b.size());
    for (int32_t p : pre) h.put(p);
    int32_t total = (int32_t)h.b.size();
    h.at<int32_t>(pTotal, total);
    h.at<int64_t>(pOff, (int64_t)total);
    h.at<int64_t>(pBulk, (int64_t)total + serial);
    ua = h.b;
}

// ---------------------------------------------------------------- pak
static Bytes readAll(const std::wstring& path, bool& ok) {
    Bytes b; ok = false;
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) return b;
    LARGE_INTEGER sz; GetFileSizeEx(f, &sz);
    if (sz.QuadPart < (1LL << 31)) {
        b.resize((size_t)sz.QuadPart); DWORD got = 0;
        ok = ReadFile(f, b.data(), (DWORD)b.size(), &got, nullptr) && got == b.size();
    }
    CloseHandle(f);
    return b;
}
// Files of a version 8/9 uncompressed pak, by name relative to its mount point ("MotorTown/Content/...").
static bool readPakFiles(const Bytes& pak, std::map<std::string, Bytes>& out, std::string& why) {
    int m = -1;
    for (int k = (int)pak.size() - 24; k >= 17 && k + 300 > (int)pak.size(); k--)
        if (memcmp(&pak[k], &PAK_MAGIC, 4) == 0) { m = k; break; }
    if (m < 0) { why = "no pak footer"; return false; }
    uint32_t ver; uint64_t off, size;
    memcpy(&ver, &pak[m + 4], 4); memcpy(&off, &pak[m + 8], 8); memcpy(&size, &pak[m + 16], 8);
    if (pak[m - 1]) { why = "encrypted index"; return false; }
    if (ver < 8 || ver > 9) { why = "pak version " + std::to_string(ver) + " (8 or 9 needed)"; return false; }
    if (off + size > pak.size()) { why = "bad index"; return false; }
    Bytes idx(pak.begin() + off, pak.begin() + off + size);
    In r(idx);
    std::string mount = r.fstr();
    int32_t n = r.get<int32_t>();
    for (int32_t k = 0; k < n && !r.bad; k++) {
        std::string name = r.fstr();
        uint64_t o = r.get<uint64_t>(), s = r.get<uint64_t>(); r.get<uint64_t>();
        uint32_t comp = r.get<uint32_t>(); r.i += 20; r.get<uint8_t>(); r.get<uint32_t>();
        if (comp) { why = "compressed entry " + name; return false; }
        const size_t hdr = 53;   // the entry's own header before its data
        if (o + hdr + s > pak.size()) { why = "entry out of range"; return false; }
        out[name] = Bytes(pak.begin() + o + hdr, pak.begin() + o + hdr + s);
    }
    if (r.bad) { why = "index truncated"; return false; }
    if (mount != "../../../") { why = "mount point " + mount; return false; }
    return true;
}
static void entry(Out& o, uint64_t off, const Bytes& data) {
    uint8_t sha[20]; hashBytes(BCRYPT_SHA1_ALGORITHM, data.data(), data.size(), sha, 20);
    o.put<uint64_t>(off); o.put<uint64_t>(data.size()); o.put<uint64_t>(data.size()); o.put<uint32_t>(0);
    o.raw(sha, 20); o.put<uint8_t>(0); o.put<uint32_t>(0);
}
// Files (name relative to "../../../", data) -> a version 8 pak.
static Bytes writePak(const std::vector<std::pair<std::string, Bytes>>& files) {
    Out p; std::vector<uint64_t> offs;
    for (auto& [n, d] : files) { offs.push_back(p.b.size()); entry(p, 0, d); p.raw(d.data(), d.size()); }
    Out idx; idx.fstr("../../../"); idx.put<int32_t>((int32_t)files.size());
    for (size_t k = 0; k < files.size(); k++) { idx.fstr(files[k].first); entry(idx, offs[k], files[k].second); }
    uint64_t io = p.b.size();
    p.raw(idx.b.data(), idx.b.size());
    uint8_t sha[20]; hashBytes(BCRYPT_SHA1_ALGORITHM, idx.b.data(), idx.b.size(), sha, 20);
    uint8_t zero[16] = {0};
    p.raw(zero, 16); p.put<uint8_t>(0); p.put(PAK_MAGIC); p.put<int32_t>(8); p.put<uint64_t>(io); p.put<uint64_t>(idx.b.size());
    p.raw(sha, 20);
    Bytes names(5 * 32, 0); p.raw(names.data(), names.size());
    return p.b;
}
// "/Game/DataAsset/Items/Items" -> "MotorTown/Content/DataAsset/Items/Items"
static std::string pakPath(const std::string& pkg) { return "MotorTown/Content/" + pkg.substr(6); }
}  // namespace fixpak
