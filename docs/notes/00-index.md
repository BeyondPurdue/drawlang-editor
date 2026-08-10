# Full Table Index

| Table | Group | Cols | PK | Access | Owner |
|---|---|---:|---|---|---|
| `abtast` | kap2_1 | 10 | `cpu1, fl_rahmen` | btree | Kleyer, LE13 |
| `ag_tmp` | kap2_1 | 8 | `cpu1, cpu2` | btree | Kleyer, LE13 |
| `bem` | kap2_1 | 3 | `plan_id, loc_id` | btree | Jendrysczyk, OI41 |
| `bg_tmp` | kap2_1 | 27 | `plan_id, loc_id` | btree | Kleyer, LE13 |
| `bpr_gru_sig` | kap2_1 | 11 | `fktbereich, inr, eanr` | btree | Pigler, LE13 |
| `bpr_gruppen` | kap2_1 | 16 | `fktbereich, inr, eanr` | btree | Pigler, LE13 |
| `bpr_in` | kap2_1 | 10 | `fktbereich, instanznr, eanr, vber` | btree | Pigler, LES3 |
| `bpr_instanz` | kap2_1 | 17 | `fktbereich, inr` | btree | Pigler, LE13 |
| `bpr_signal` | kap2_1 | 20 | `fktbereich, inr, eanr` | btree | Pigler, LE13 |
| `ct_bg` | kap2_1 | 8 | `-` | - | Kuwertz, LES3 |
| `ct_bgt` | kap2_1 | 12 | `-` | - | Kuwertz, LES3 |
| `ct_instanz` | kap2_1 | 23 | `-` | - | Kuwertz, LES3 |
| `ct_signal` | kap2_1 | 11 | `-` | - | Kuwertz, LES3 |
| `dbodat` | kap2_1 | 8 | `cpu1,cpu4,rk` | btree | Lenhart, LE13 |
| `dx_1` | kap2_1 | 4 | `keine` | - | Kleyer, LES3 |
| `dx_140` | kap2_1 | 10 | `as_nr, w_adr, b_adr` | btree | Kleyer, LE13 |
| `dx_1_body` | kap2_1 | 4 | `keine` | - | Kleyer, LES3 |
| `ergebnis` | kap2_1 | 22 | `ag_nr, kp_nr, pb_nr, z_nr` | btree | Kleyer, LE13 |
| `fb_d` | kap2_1 | 17 | `fb_id` | btree | Keim, LE13 |
| `fkz_d` | kap2_1 | 16 | `fkz_id` | btree | Keim, LE13 |
| `funktion` | kap2_1 | 30 | `kennzeichen` | btree | - |
| `fx_idnr` | kap2_1 | 17 | `keine` | heap | Kleyer, LE13 |
| `geraete` | kap2_1 | 27 | `kennzeichen, nr` | btree | - |
| `inst_default` | kap2_1 | 9 | `keine` | heap | Kleyer, LE13 |
| `konnektor` | kap2_1 | 11 | `plan_id, se` | btree | Keim, LE13 |
| `lan_block` | kap2_1 | 16 | `keine` | heap | Waller, |
| `lan_status` | kap2_1 | 3 | `plan_id, loc_id` | btree | Kleyer, LE13 |
| `lan_verbindung` | kap2_1 | 26 | `keine` | heap | - |
| `lt_f` | kap2_1 | 10 | `plan_id, kks` | btree | Kleyer, LE13 |
| `mmi_obj_f` | kap2_1 | 10 | `plan_id` | btree | Pigler, LE13 |
| `obj_d` | kap2_1 | 11 | `plan_id, se` | btree | Lenhart, LE13 |
| `obj_f` | kap2_1 | 17 | `plan_id` | btree | Jendrysczyk, OI41 |
| `obj_g` | kap2_1 | 18 | `plan_id, se` | btree | Jendrysczyk, OI41 |
| `obj_inst` | kap2_1 | 6 | `plan_id, loc_id` | btree | - |
| `obj_kakb` | kap2_1 | 10 | `cpu1, cpu2, tn, bn, ka, typ, bg_id` | btree | Lenhart, LE13 |
| `obj_s` | kap2_1 | 42 | `plan_id` | btree | Mertens, OI41 |
| `om_asr_as` | kap2_1 | 3 | `keine` | heap | Pigler, LE13 |
| `om_asr_as_fb` | kap2_1 | 2 | `keine` | heap | Pigler, LE13 |
| `om_ver` | kap2_1 | 5 | `plan_id, loc_id, port_nr` | - | Pigler, LE13 |
| `pb_list` | kap2_1 | 6 | `cpu1, cpu2, cpu4` | btree | Dr. Unkelbach OI41 |
| `pd_proj` | kap2_1 | 3 | `nam_pd` | btree | Pigler, LE13 |
| `pro_d` | kap2_1 | 11 | `pro_id` | heap | Keim, LE13 |
| `proc_queue` | kap2_1 | 13 | `plan_id` | btree | Dr. Unkelbach, OI41 |
| `re_proj` | kap2_1 | 8 | `fktbereich, inr, eanr` | btree | Pigler, LE13 |
| `re_proj_hilf` | kap2_1 | 8 | `fktbereich, inr, eanr` | btree | Pigler, LE13 |
| `regel_cpy` | kap2_1 | 6 | `keine` | heap | Fiedler, OI41 |
| `rs_proj` | kap2_1 | 6 | `repo_no` | btree | Pigler, LE13 |
| `rs_proj_hilf` | kap2_1 | 6 | `repo_no` | btree | Pigler, LE13 |
| `rv_proj` | kap2_1 | 24 | `repo_no` | btree | Pigler, LE13 |
| `rv_proj_hilf` | kap2_1 | 22 | `repo_no` | btree | Pigler, LE13 |
| `s5_abtast` | kap2_1 | 3 | `keine` | heap | Lenhart, LE13 |
| `s5_ag_daten` | kap2_1 | 11 | `cpu1, cpu1_kom` | btree | Kleyer, LE13 |
| `s5_config` | kap2_1 | 7 | `keine` | heap | Kleyer, LE13 |
| `s5_reg_erg` | kap2_1 | 15 | `cpu1, cpu4` | isam | Lenhart, LE13 |
| `schr_d` | kap2_1 | 4 | `plan_id, se` | btree | Keim, LE13 |
| `simulation` | kap2_1 | 23 | `-` | - | - |
| `so_admi` | kap2_1 | 3 | `nr_sto, oeid_sto, oen_sto` | brtee | Pigler, LE13 |
| `so_admi_hilf` | kap2_1 | 3 | `nr_sto, oeid_sto, oen_sto` | brtee | Pigler, LE13 |
| `st_admi` | kap2_1 | 15 | `nr_st` | btree | Pigler, LE13 |
| `st_admi_hilf` | kap2_1 | 13 | `nr_st` | btree | Pigler, LE13 |
| `status` | kap2_1 | 11 | `plan_id` | btree | Jendrysczyk, OI41 |
| `ver_b` | kap2_1 | 23 | `plan_id, se` | btree | Keim, LE13 |
| `vf_zuli` | kap2_1 | 3 | `zuli_id` | btree | Pigler, LE13 |
| `zuli` | kap2_1 | 21 | `zuli_id` | btree | Keim, LE13 |
| `zuli_kanal` | kap2_1 | 34 | `kks, sig` | btree | Kleyer, LE13 |
| `bpr_typ` | kap2_2 | 7 | `keine` | heap | Pigler, LE13 |
| `bpr_typea` | kap2_2 | 14 | `ityp, eanr` | btree | Pigler, LE13 |
| `bst_allg` | kap2_2 | 14 | `id` | isam | - |
| `bst_allg_spra` | kap2_2 | 4 | `id` | isam | - |
| `bst_bit` | kap2_2 | 19 | `id` | isam | - |
| `bst_bit_spra` | kap2_2 | 4 | `id` | isam | - |
| `bst_ea` | kap2_2 | 36 | `id, ea_nr` | isam | - |
| `bst_ea_spra` | kap2_2 | 8 | `id, ea_nr` | isam | - |
| `bst_for` | kap2_2 | 18 | `id` | isam | - |
| `bst_xp` | kap2_2 | 8 | `id` | isam | - |
| `bst_xp_erw` | kap2_2 | 4 | `id` | isam, f_nr | - |
| `bst_xp_ver` | kap2_2 | 11 | `art,bst_nr,ausg_st` | isam | - |
| `cmd` | kap2_2 | 2 | `spra` | isam | Keim, LE13 |
| `cmd_hdl` | kap2_2 | 5 | `spra` | isam | Keim, LE13 |
| `cmd_ln` | kap2_2 | 6 | `spra` | isam | Keim, LE13 |
| `frame` | kap2_2 | 1 | `frm_id` | isam | Keim, LE13 |
| `hw_regel` | kap2_2 | 11 | `hw_pic_id` | btree | Dr. Unkelbach, OI41 |
| `mmi_dyx` | kap2_2 | 2 | `dyx_id` | isam | - |
| `msk_b` | kap2_2 | 6 | `msk_id` | btree | Keim, LE13 |
| `msk_g` | kap2_2 | 7 | `msk_id, lau` | btree | Keim, LE13 |
| `om_asr_bst_allg` | kap2_2 | 4 | `keine` | heap | Pigler, LE13 |
| `om_asr_bst_ea` | kap2_2 | 17 | `keine` | heap | Pigler, LE13 |
| `pic_b` | kap2_2 | 18 | `grp, pic_id` | btree | Hartz, LE13 |
| `pic_d` | kap2_2 | 25 | `pic_id, param_nr` | btree | Betz, LE13 |
| `pic_dmz` | kap2_2 | 7 | `pic_id, port_nr` | btree | Pigler, LE13 |
| `pic_ex` | kap2_2 | 3 | `pic_id, lau` | cbtree | Keim, LE13 |
| `pic_kanal` | kap2_2 | 6 | `pic_id, ka, txp_id` | btree | Kleyer, LE13 |
| `pic_ltf` | kap2_2 | 5 | `txp_id, ea_nr, sprache` | btree | Hartz, LE13 |
| `pic_m` | kap2_2 | 4 | `pic_id,msk_nr` | - | Höning, LE13 |
| `pic_msr` | kap2_2 | 5 | `transfer_id, pic_id, attribut_nam` | isam | , LE13 |
| `pic_p` | kap2_2 | 13 | `pic_id, port_nr` | btree | Betz, LE13 |
| `pic_status` | kap2_2 | 11 | `pic_id` | - | Ott, LE13 |
| `pic_tt` | kap2_2 | 7 | `pic_id, port_nr, sprache` | btree | Pigler, LE13 |
| `pic_w` | kap2_2 | 4 | `wf_id` | btree | Keim, LE13 |
| `pr_m` | kap2_2 | 3 | `pr_m_id` | btree | Keim, LE13 |
| `pr_w` | kap2_2 | 5 | `pr_w_id` | btree | Keim, LE13 |
| `prf_regel` | kap2_2 | 7 | `regel_id, class_id, pic_id` | btree | Dr. Unkelbach, OI41 |
| `raster` | kap2_2 | 6 | `keine` | heap | Keim, LE13 |
| `regel` | kap2_2 | 7 | `q_bea_typ, z_bea_typ` | heap | Keim, LE13 |
| `std_bupl` | kap2_2 | 2 | `bupl` | isam | Hartz, LE13 |
| `anpass` | kap2_3 | 1 | `keine` | heap | Höning |
| `ck_queue` | kap2_3 | 5 | `plan_id` | btree | Fiedler, OI41 |
| `error` | kap2_3 | 3 | `spra` | isam | Keim, LE13 |
| `pr_queue` | kap2_3 | 13 | `job, name` | btree | Fiedler, OI41 |
| `reptext` | kap2_3 | 5 | `keine` | heap | Ermer, ANL A433 SI |
| `summary` | kap2_3 | 11 | `keine` | heap | Jendrysczyk, OI41 |
| `uas_d` | kap2_3 | 5 | `uas_id` | isam | Dr. Unkelbach, OI41 |
| `users` | kap2_3 | 2 | `abb` | isam | Pfeuffer, LE13 |
| `version` | kap2_3 | 3 | `node` | isam | Höning, LE13 |
| `zlnr` | kap2_3 | 5 | `keine` | heap | Keim, LE13 |
| `std_konnektor` | kap2_4 | 11 | `plan_id, se` | btree | Dr. Unkelbach OI41 |
| `std_obj_d` | kap2_4 | 11 | `plan_id, se` | btree | Dr. Unkelbach OI41 |
| `std_obj_f` | kap2_4 | 17 | `plan_id` | btree | Dr. Unkelbach OI41 |
| `std_obj_g` | kap2_4 | 18 | `plan_id, se` | btree | Dr. Unkelbach OI41 |
| `std_schr_d` | kap2_4 | 4 | `plan_id, se` | btree | Dr. Unkelbach OI41 |
| `std_summary` | kap2_4 | 7 | `keine` | heap | Dr. Unkelbach OI41 |
| `std_ver_b` | kap2_4 | 26 | `plan_id, se` | btree | Dr. Unkelbach OI41 |
| `std_zuli` | kap2_4 | 21 | `zuli_id` | btree | Dr. Unkelbach OI41 |
| `bp_pic` | kap2_5 | 8 | `keine` | heap | Lenhart, LE13 |
| `cg_bea` | kap2_5 | 2 | `bea_typ` | isam | Kleyer, LE13 |
| `cg_bgrang` | kap2_5 | 7 | `keine` | heap | Kleyer, LE13 |
| `cg_bgsitopp` | kap2_5 | 5 | `keine` | heap | - |
| `cg_config_ag` | kap2_5 | 8 | `cpu1, cpu2` | btree | Kleyer, LE13 |
| `cg_config_ag_db_inter` | kap2_5 | 7 | `-` | heap | Kleyer, LE13 |
| `cg_config_ag_fnr` | kap2_5 | 4 | `cpu1, cpu4` | btree | Kleyer, LE13 |
| `cg_config_h1` | kap2_5 | 15 | `keine` | - | Kleyer, LE13 |
| `cg_config_pb` | kap2_5 | 6 | `keine` | heap | Kleyer, LE13 |
| `cg_config_tz_bau` | kap2_5 | 7 | `cpu1, cpu2, modus, anf_nr` | btree | Kleyer, LE13 |
| `cg_error` | kap2_5 | 3 | `id` | - | Kleyer, LE13 |
| `cg_kks_sitopp` | kap2_5 | 15 | `keine` | heap | - |
| `cg_maco` | kap2_5 | 3 | `opkenn` | btree | Kleyer, LE13 |
| `cg_pic_b` | kap2_5 | 9 | `pic_id` | isam | Kleyer, LE13 |
| `cg_pic_d` | kap2_5 | 9 | `pic_id, param_nr` | isam | Kleyer, LE13 |
| `cg_pic_p` | kap2_5 | 7 | `pic_id, port_nr` | isam | Kleyer, LE13 |
| `cg_step` | kap2_5 | 6 | `pic_id, port_nr` | btree | Kleyer, LE13 |
| `dbb_hlp0` | kap2_5 | 6 | `pic_id` | isam | Lenhart, LE13 |
| `lan_regel` | kap2_5 | 4 | `regel_id, regelname` | btree | Kleyer, LE13 |
| `pic_r` | kap2_5 | 4 | `r_id` | isam | Lenhart, LE13 |
| `s5_apf_schutzmaske` | kap2_5 | 8 | `keine` | heap | Kleyer, LE13 |
| `s5_bg` | kap2_5 | 26 | `pic_id, bg_id` | isam | Lenhart, LE13 |
| `s5_bg_fs` | kap2_5 | 8 | `bg_id, pic_id, bgr` | isam | Lenhart, LE13 |
| `s5_db_i` | kap2_5 | 13 | `pic_id, bst_id` | isam | Lenhart, LE13 |
| `s5_ele_dx` | kap2_5 | 12 | `bg_id, param_nr, dw` | isam | Lenhart, LE13 |
| `s5_ele_sm` | kap2_5 | 9 | `bg_id, bel, ka, param_nr` | isam | Lenhart, LE13 |
| `s5_fb` | kap2_5 | 10 | `pic_id, bst_id` | isam | Lenhart, LE13 |
| `s5_gle_db` | kap2_5 | 10 | `bst_id, param_nr, w_adr` | isam | Lenhart, LE13 |
| `s5_kle_db` | kap2_5 | 14 | `bst_id, param_nr, dw` | isam | Lenhart, LE13 |
| `s5_kon_db` | kap2_5 | 4 | `keine` | heap | Lenhart, LE13 |
| `s5_pg` | kap2_5 | 2 | `keine` | heap | Lenhart, LE13 |
| `s5_pic_reg` | kap2_5 | 10 | `pic_id, bst_id` | isam | Lenhart, LE13 |
| `s5_stplz` | kap2_5 | 3 | `keine` | heap | Lenhart, LE13 |