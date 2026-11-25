// Tests for plugins\zmt_fixpak.hpp.
//   zmt_fixpak_test                      self-check: hashes, name split, composite and pak round trips
//   zmt_fixpak_test <framework.pak> <out.pak>
//       every composite in the framework pak, copied with one extra parent per composite (/Game/ZMTTest/...), packed
//       into out.pak -- for checking with repak and UAssetGUI (tools\zmt_fixpak_check.py).
#include <cstdio>
#include "../plugins/zmt_fixpak.hpp"
using namespace fixpak;

static int fails = 0;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

static void selfTest() {
    // hashes stored in the framework's cooked Decals composite
    CHECK(nameHashes("/Game/UI/Icons/Licensed/Buff/Coffee") == (0x7c88u | (0xbd6bu << 16)));
    CHECK(nameHashes("Buff_Coffee") == (0x915fu | (0xe226u << 16)));
    CHECK(splitName("LSD_Clutch_2_100_40") == std::make_pair(std::string("LSD_Clutch_2_100"), 41));
    CHECK(splitName("Cargos_01") == std::make_pair(std::string("Cargos_01"), 0));
    CHECK(splitName("Ch_0") == std::make_pair(std::string("Ch"), 1));
    CHECK(splitName("Items") == std::make_pair(std::string("Items"), 0));

    Composite c;
    c.pkg = "/Game/DataAsset/Items/Items"; c.name = "Items";
    c.structPkg = "/Script/MotorTown"; c.structName = "MTItemRow";
    c.parents = {{"/Game/DataAsset/Items/Items_0", "Items_0", "DataTable"},
                 {"/Game/Hubs/X/Items_X", "Items_X", "CompositeDataTable"},
                 {"/Game/Mods/Y/Items_Y_3", "Items_Y_3", "DataTable"},
                 {"/Game/DataAsset/Items/Items_0", "Items_0", "DataTable"}};   // twice: written once
    Out t; t.fstr("RowName"); t.put<int32_t>(0); c.tail = t.b;
    Bytes ua, ue;
    buildComposite(c, ua, ue);
    Composite back; std::string why;
    CHECK(parseComposite(ua, ue, back, why));
    CHECK(back.pkg == c.pkg && back.name == c.name && back.structName == "MTItemRow" && back.structPkg == "/Script/MotorTown");
    CHECK(back.parents.size() == 3 && back.parents[1].cls == "CompositeDataTable" && back.parents[2].pkg == "/Game/Mods/Y/Items_Y_3");
    CHECK(back.tail == c.tail);
    Bytes ua2, ue2; buildComposite(back, ua2, ue2);
    CHECK(ua2 == ua && ue2 == ue);                                    // deterministic
    Bytes pak = writePak({{pakPath(c.pkg) + ".uasset", ua}, {pakPath(c.pkg) + ".uexp", ue}});
    std::map<std::string, Bytes> files;
    CHECK(readPakFiles(pak, files, why));
    CHECK(files.size() == 2 && files["MotorTown/Content/DataAsset/Items/Items.uasset"] == ua && files["MotorTown/Content/DataAsset/Items/Items.uexp"] == ue);
}

static int frameworkCopy(const char* in, const char* out) {
    bool ok; std::string p(in);
    Bytes pak = readAll(std::wstring(p.begin(), p.end()), ok);
    std::map<std::string, Bytes> files; std::string why;
    if (!ok || !readPakFiles(pak, files, why)) { printf("cannot read %s: %s\n", in, why.c_str()); return 1; }
    std::vector<std::pair<std::string, Bytes>> outFiles;
    for (auto& [n, ua] : files) {
        if (n.size() < 7 || n.compare(n.size() - 7, 7, ".uasset")) continue;
        std::string base = n.substr(0, n.size() - 7);
        Composite c;
        if (!parseComposite(ua, files[base + ".uexp"], c, why)) { printf("  %s: %s\n", base.c_str(), why.c_str()); continue; }
        c.parents.push_back({"/Game/ZMTTest/" + c.name + "_ZMTTest_2", c.name + "_ZMTTest_2", "DataTable"});
        Bytes a, e; buildComposite(c, a, e);
        outFiles.push_back({base + ".uasset", a}); outFiles.push_back({base + ".uexp", e});
        printf("  %s: %s.%s, %zu parents\n", c.id().c_str(), c.structPkg.c_str(), c.structName.c_str(), c.parents.size());
    }
    Bytes o = writePak(outFiles);
    FILE* f = fopen(out, "wb"); if (!f) return 1;
    fwrite(o.data(), 1, o.size(), f); fclose(f);
    printf("wrote %s (%zu files)\n", out, outFiles.size());
    return 0;
}

int main(int argc, char** argv) {
    if (argc == 3) return frameworkCopy(argv[1], argv[2]);
    selfTest();
    printf(fails ? "zmt_fixpak tests: %d failed\n" : "zmt_fixpak tests ok\n", fails);
    return fails ? 1 : 0;
}
