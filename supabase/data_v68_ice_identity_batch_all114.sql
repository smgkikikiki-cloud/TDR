-- Ice new-identity batch 'ice-2569-09-all114': all 114 owner-decided models (owner confirmed the 5 alias-collision ones are new models; new brands Asia Cab and Lepas approved).
-- Needs v68 applied first. SAFE BY DEFAULT: ends with ROLLBACK (changes nothing, only shows result).
-- To really create: change the last line 'rollback;' to 'commit;' and run again. Undo: select vm_revert_identity_batch('ice-2569-09-all114');
begin;
select vm_create_identities('ice-2569-09-all114', '[
{
"canonical_id": "audi.r8_spyder_v10",
"brand_name_en": "Audi",
"name_en": "R8 Spyder V10",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"adb3def47c5d6170\"]"
},
{
"canonical_id": "changan.star_truck",
"brand_name_en": "Changan",
"name_en": "Changan Star Truck",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"5aa4b0d8b487cc8a\"]"
},
{
"canonical_id": "chevrolet.optra",
"brand_name_en": "Chevrolet",
"name_en": "Chevrolet Optra",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"bdd401ca0b1a5065\"]"
},
{
"canonical_id": "ferrari.812",
"brand_name_en": "Ferrari",
"name_en": "Ferrari 812",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"dddf5981f82198d6\"]"
},
{
"canonical_id": "ferrari.california",
"brand_name_en": "Ferrari",
"name_en": "Ferrari California",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"0541dd6b156939d3\"]"
},
{
"canonical_id": "ferrari.f12_tdf",
"brand_name_en": "Ferrari",
"name_en": "Ferrari F12 TDF",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"c707f375e8c424af\"]"
},
{
"canonical_id": "ferrari.f360",
"brand_name_en": "Ferrari",
"name_en": "Ferrari F360",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"29f77d8e21505f4d\"]"
},
{
"canonical_id": "ford.ecosport",
"brand_name_en": "Ford",
"name_en": "Ford EcoSport",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"0ee753f8c64adca0\"]"
},
{
"canonical_id": "ford.fiesta",
"brand_name_en": "Ford",
"name_en": "Ford Fiesta",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"4ef7bf29b09bb2b6\"]"
},
{
"canonical_id": "ford.territory",
"brand_name_en": "Ford",
"name_en": "Ford Territory",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"c8af6e029d9f78a6\"]"
},
{
"canonical_id": "honda.n_van",
"brand_name_en": "Honda",
"name_en": "Honda N-VAN",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:164\"]"
},
{
"canonical_id": "honda.nsx_type_s",
"brand_name_en": "Honda",
"name_en": "Honda NSX Type S",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"934f4a1929d70e6c\"]"
},
{
"canonical_id": "hyundai.county",
"brand_name_en": "Hyundai",
"name_en": "Hyundai County",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"b46d6088d3761fde\"]"
},
{
"canonical_id": "hyundai.sonata",
"brand_name_en": "Hyundai",
"name_en": "Hyundai Sonata",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"ec89df59eefd9a4a\"]"
},
{
"canonical_id": "hyundai.veloster",
"brand_name_en": "Hyundai",
"name_en": "Hyundai Veloster",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"007e3b92c2d87e00\"]"
},
{
"canonical_id": "kia.soul",
"brand_name_en": "Kia",
"name_en": "Kia Soul",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"954a170bba32fa52\"]"
},
{
"canonical_id": "kia.soul_ev",
"brand_name_en": "Kia",
"name_en": "Kia Soul EV",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"df6beeee8b10711d\"]"
},
{
"canonical_id": "mg.gs",
"brand_name_en": "Mg",
"name_en": "MG GS",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:288\"]"
},
{
"canonical_id": "mg.mg6",
"brand_name_en": "Mg",
"name_en": "MG6",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"c122bc6d00754321\"]"
},
{
"canonical_id": "sokon.ec31",
"brand_name_en": "Sokon",
"name_en": "Sokon EC31",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"ec156868f11e3f1a\"]"
},
{
"canonical_id": "toyota.coaster",
"brand_name_en": "Toyota",
"name_en": "Toyota Coaster",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:477\"]"
},
{
"canonical_id": "toyota.hilux_vigo",
"brand_name_en": "Toyota",
"name_en": "Toyota Hilux Vigo",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"42a67a816c726a6e\"]"
},
{
"canonical_id": "toyota.mirai",
"brand_name_en": "Toyota",
"name_en": "Toyota Mirai",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"cb5ace255bbbc3e2\"]"
},
{
"canonical_id": "volvo.v90",
"brand_name_en": "Volvo",
"name_en": "Volvo V90",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"c2659838d910ca36\"]"
},
{
"canonical_id": "asia_cab.as4",
"brand_name_en": "Asia Cab",
"name_en": "Asia Cab AS4",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:598\"]"
},
{
"canonical_id": "audi.a3",
"brand_name_en": "Audi",
"name_en": "Audi A3",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"9f8ae7e8a2b0bcbf\"]"
},
{
"canonical_id": "audi.a8l",
"brand_name_en": "Audi",
"name_en": "A8L",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:612\"]"
},
{
"canonical_id": "audi.q6",
"brand_name_en": "Audi",
"name_en": "Audi Q6",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"bdccbdecad7cd55a\"]"
},
{
"canonical_id": "audi.rs_3",
"brand_name_en": "Audi",
"name_en": "Audi RS 3",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"35e5416826b727de\"]"
},
{
"canonical_id": "audi.rs_4",
"brand_name_en": "Audi",
"name_en": "Audi RS 4",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"31db27fa51c287f8\"]"
},
{
"canonical_id": "audi.rs_5",
"brand_name_en": "Audi",
"name_en": "Audi RS 5",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"4314b2408d93afa4\"]"
},
{
"canonical_id": "audi.rs_6",
"brand_name_en": "Audi",
"name_en": "Audi RS 6",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"f51ec28f34641456\"]"
},
{
"canonical_id": "audi.rs_7",
"brand_name_en": "Audi",
"name_en": "Audi RS 7",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"8f04a87b22ff06ea\"]"
},
{
"canonical_id": "audi.rs_q3",
"brand_name_en": "Audi",
"name_en": "Audi RS Q3",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"0c4c6e48dd4fbe3e\"]"
},
{
"canonical_id": "audi.rs_q7",
"brand_name_en": "Audi",
"name_en": "Audi RS Q7",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"a6f0ebb257154abc\"]"
},
{
"canonical_id": "audi.s3",
"brand_name_en": "Audi",
"name_en": "S3",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:626\"]"
},
{
"canonical_id": "audi.r8",
"brand_name_en": "Audi",
"name_en": "Audi R8",
"status": "HISTORICAL",
"note": "Ice owner-decided new identity [\"d63f424e20065d85\"]"
},
{
"canonical_id": "bentley.continental",
"brand_name_en": "Bentley",
"name_en": "Continental",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:641\"]"
},
{
"canonical_id": "bmw.8_series",
"brand_name_en": "Bmw",
"name_en": "BMW 8 Series",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"b2d7961ea909bbed\"]"
},
{
"canonical_id": "bmw.430i",
"brand_name_en": "Bmw",
"name_en": "BMW 430i",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:662\"]"
},
{
"canonical_id": "bmw.530e",
"brand_name_en": "Bmw",
"name_en": "530e",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:665\"]"
},
{
"canonical_id": "bmw.630i",
"brand_name_en": "Bmw",
"name_en": "BMW 630I",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:666\"]"
},
{
"canonical_id": "bmw.m2",
"brand_name_en": "Bmw",
"name_en": "M2",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:674\"]"
},
{
"canonical_id": "bmw.m3",
"brand_name_en": "Bmw",
"name_en": "BMW M3",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:675\"]"
},
{
"canonical_id": "bmw.m4",
"brand_name_en": "Bmw",
"name_en": "BMW M4",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:676\"]"
},
{
"canonical_id": "bmw.m5",
"brand_name_en": "Bmw",
"name_en": "BMW M5",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:677\"]"
},
{
"canonical_id": "bmw.x2",
"brand_name_en": "Bmw",
"name_en": "X2",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:693\"]"
},
{
"canonical_id": "byd.e6",
"brand_name_en": "Byd",
"name_en": "e6",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:700\"]"
},
{
"canonical_id": "chery.q",
"brand_name_en": "Chery",
"name_en": "Chery Q",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:715\"]"
},
{
"canonical_id": "ferrari.488",
"brand_name_en": "Ferrari",
"name_en": "488",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:740\"]"
},
{
"canonical_id": "ferrari.purosangue",
"brand_name_en": "Ferrari",
"name_en": "Ferrari Purosangue",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:743\"]"
},
{
"canonical_id": "ford.ranger_raptor_double_cab",
"brand_name_en": "Ford",
"name_en": "Ranger Raptor Double Cab",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:751\"]"
},
{
"canonical_id": "foton.eview",
"brand_name_en": "Foton",
"name_en": "Foton eView",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:756\"]"
},
{
"canonical_id": "foton.cp_foton_tm_i_blue_45",
"brand_name_en": "Foton",
"name_en": "CP Foton TM i-Blue 45",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:757\"]"
},
{
"canonical_id": "foton.tunland",
"brand_name_en": "Foton",
"name_en": "Foton Tunland",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:764\"]"
},
{
"canonical_id": "gwm.ora_07",
"brand_name_en": "Gwm",
"name_en": "GWM Ora 07",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:772\"]"
},
{
"canonical_id": "gwm.ora_5",
"brand_name_en": "Gwm",
"name_en": "Ora 5",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:773\"]"
},
{
"canonical_id": "hino.xzu600r_wkmlst3",
"brand_name_en": "Hino",
"name_en": "HINO XZU600R-WKMLST3",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:786\"]"
},
{
"canonical_id": "honda.brio",
"brand_name_en": "Honda",
"name_en": "Brio",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:791\"]"
},
{
"canonical_id": "honda.acty",
"brand_name_en": "Honda",
"name_en": "Acty",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:798\"]"
},
{
"canonical_id": "honda.e",
"brand_name_en": "Honda",
"name_en": "Honda e",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:800\"]"
},
{
"canonical_id": "honda.freed",
"brand_name_en": "Honda",
"name_en": "Freed",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:802\"]"
},
{
"canonical_id": "honda.jazz",
"brand_name_en": "Honda",
"name_en": "Jazz",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:809\"]"
},
{
"canonical_id": "honda.super_one",
"brand_name_en": "Honda",
"name_en": "Honda Super-ONE",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:815\"]"
},
{
"canonical_id": "hyundai.elantra_n",
"brand_name_en": "Hyundai",
"name_en": "Hyundai Elantra N",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"a4557f9d2143388c\"]"
},
{
"canonical_id": "hyundai.kona",
"brand_name_en": "Hyundai",
"name_en": "Kona",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:825\"]"
},
{
"canonical_id": "jaecoo.j6",
"brand_name_en": "Jaecoo",
"name_en": "J6",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:839\"]"
},
{
"canonical_id": "jeep.gladiator",
"brand_name_en": "Jeep",
"name_en": "Gladiator",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:857\"]"
},
{
"canonical_id": "land_rover.discovery",
"brand_name_en": "Land Rover",
"name_en": "Land Rover Discovery",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:880\"]"
},
{
"canonical_id": "lepas.l6",
"brand_name_en": "Lepas",
"name_en": "Lepas L6",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:884\"]"
},
{
"canonical_id": "lexus.rc",
"brand_name_en": "Lexus",
"name_en": "RC",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:895\"]"
},
{
"canonical_id": "lotus.elise",
"brand_name_en": "Lotus",
"name_en": "Lotus Elise",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"6c77cf04a461f95c\"]"
},
{
"canonical_id": "lotus.emira",
"brand_name_en": "Lotus",
"name_en": "Emira",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:903\"]"
},
{
"canonical_id": "mg.maxus_v80",
"brand_name_en": "Mg",
"name_en": "Maxus V80",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:917\"]"
},
{
"canonical_id": "mazda.mx_30",
"brand_name_en": "Mazda",
"name_en": "MX-30",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:925\"]"
},
{
"canonical_id": "mazda.mazda6e",
"brand_name_en": "Mazda",
"name_en": "Mazda6e",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:931\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_amg_c",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz AMG C",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:938\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_amg_g63",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz AMG G63",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:939\"]"
},
{
"canonical_id": "mercedes_benz.c350",
"brand_name_en": "Mercedes Benz",
"name_en": "C350",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:943\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_cla_class",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz CLA-Class",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:944\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_cle_class",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz CLE-Class",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:945\"]"
},
{
"canonical_id": "mercedes_benz.e300",
"brand_name_en": "Mercedes Benz",
"name_en": "E300",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:948\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_eqb_class",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz EQB-Class",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:949\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_eqe_class",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz EQE-Class",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:950\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_eqs_class",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz EQS-Class",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:951\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_glb_class",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz GLB-Class",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:953\"]"
},
{
"canonical_id": "mercedes_benz.mercedes_benz_s350d",
"brand_name_en": "Mercedes Benz",
"name_en": "Mercedes-Benz S350D",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:956\"]"
},
{
"canonical_id": "mg.urban_ev",
"brand_name_en": "Mg",
"name_en": "Urban EV",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:976\"]"
},
{
"canonical_id": "mitsubishi.pajero",
"brand_name_en": "Mitsubishi",
"name_en": "Mitsubishi Pajero",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"690b8d9fbc18980f\"]"
},
{
"canonical_id": "nissan.leaf",
"brand_name_en": "Nissan",
"name_en": "Leaf",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1014\"]"
},
{
"canonical_id": "nissan.fairlady",
"brand_name_en": "Nissan",
"name_en": "Nissan Fairlady",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1019\"]"
},
{
"canonical_id": "nissan.march",
"brand_name_en": "Nissan",
"name_en": "Nissan March",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1021\"]"
},
{
"canonical_id": "nissan.urvan_e26",
"brand_name_en": "Nissan",
"name_en": "Nissan Urvan E26",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1026\"]"
},
{
"canonical_id": "nissan.note",
"brand_name_en": "Nissan",
"name_en": "Nissan Note",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1028\"]"
},
{
"canonical_id": "nissan.urvan",
"brand_name_en": "Nissan",
"name_en": "Nissan Urvan",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1033\"]"
},
{
"canonical_id": "peugeot.408",
"brand_name_en": "Peugeot",
"name_en": "408",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1037\"]"
},
{
"canonical_id": "peugeot.5008",
"brand_name_en": "Peugeot",
"name_en": "5008",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1038\"]"
},
{
"canonical_id": "seres.ec31",
"brand_name_en": "Seres",
"name_en": "EC31",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1058\"]"
},
{
"canonical_id": "sokon.crc50",
"brand_name_en": "Sokon",
"name_en": "CRC50",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1060\"]"
},
{
"canonical_id": "subaru.levorge",
"brand_name_en": "Subaru",
"name_en": "Subaru levorge",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"fa7d4ad29e3d3907\"]"
},
{
"canonical_id": "suzuki.spacia",
"brand_name_en": "Suzuki",
"name_en": "Suzuki Spacia",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1081\"]"
},
{
"canonical_id": "toyota.gr_corolla",
"brand_name_en": "Toyota",
"name_en": "Toyota GR Corolla",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"f7a3c07aad0a2eac\"]"
},
{
"canonical_id": "toyota.gr_yaris",
"brand_name_en": "Toyota",
"name_en": "Toyota GR Yaris",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1123\"]"
},
{
"canonical_id": "toyota.land_cruiser",
"brand_name_en": "Toyota",
"name_en": "Toyota Land Cruiser",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1133\"]"
},
{
"canonical_id": "toyota.land_cruiser_fj",
"brand_name_en": "Toyota",
"name_en": "Toyota Land Cruiser FJ",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1134\"]"
},
{
"canonical_id": "toyota.roomy",
"brand_name_en": "Toyota",
"name_en": "Toyota Roomy",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1144\"]"
},
{
"canonical_id": "toyota.sienta",
"brand_name_en": "Toyota",
"name_en": "Sienta",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1145\"]"
},
{
"canonical_id": "toyota.tr",
"brand_name_en": "Toyota",
"name_en": "Toyota TR",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1146\"]"
},
{
"canonical_id": "toyota.vios",
"brand_name_en": "Toyota",
"name_en": "Vios",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1149\"]"
},
{
"canonical_id": "volkswagen.touareg",
"brand_name_en": "Volkswagen",
"name_en": "Volkswagen Touareg",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1171\"]"
},
{
"canonical_id": "volt.volt",
"brand_name_en": "Volt",
"name_en": "VOLT Volt",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1175\"]"
},
{
"canonical_id": "volvo.c40",
"brand_name_en": "Volvo",
"name_en": "Volvo C40",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"cd9af6faa42a4715\"]"
},
{
"canonical_id": "volvo.es90",
"brand_name_en": "Volvo",
"name_en": "ES90",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1179\"]"
},
{
"canonical_id": "zeekr.7x",
"brand_name_en": "Zeekr",
"name_en": "7X",
"status": "UNVERIFIED",
"note": "Ice owner-decided new identity [\"owner-overlay-line:1199\"]"
}
]'::jsonb, 'owner');
rollback;
