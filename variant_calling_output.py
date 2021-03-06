
def create_varing_calling_output(ref, upd_ref, base_states, xtilde):

    variants = ""
    variant_list = []

    # For Difference between reference and updated reference
    gap_counter = 0

    for i in range(len(ref)):
        if xtilde[i + gap_counter] == 0 or xtilde[i + gap_counter] == 29 or xtilde[i + gap_counter] == -1:
            # Case: nothing new
            if upd_ref[i + gap_counter] == "-":
                gap_counter = gap_counter + 1
            continue

        elif upd_ref[i + gap_counter] == "-":
            # Case: Gaps Insertions in updated reference
            gap_counter = gap_counter + 1
            this_gap_number = 1
            gap_control = True

            while gap_control:
                # Checking if there are more than one Gap in updated reference:
                if upd_ref[i + gap_counter] == "-":
                    gap_counter = gap_counter + 1
                    this_gap_number = this_gap_number + 1
                else:
                    gap_control = False

            for ii in range(this_gap_number):
                # Handle the gaps:
                if ii == 0:
                    if base_states[i + ii][0] == base_states[i + ii][1]:
                        # e.g. 2345 A AC

                        variants = str(
                            i) + " \t " + str(ref[i - 1]) + " \t " + str(ref[i - 1]) + str(base_states[i + ii][0])

                    elif base_states[i + ii][0] != base_states[i + ii][1] and base_states[i + ii][0] != "-" and base_states[i + ii][1] != "-":
                        # e.g. 2345 A AC,AG

                        variants = str(i) + " \t " + str(ref[i - 1]) + " \t " + str(ref[i - 1]) + str(
                            base_states[i + ii][0]) + "," + str(ref[i - 1]) + str(base_states[i + ii][1])

                    elif base_states[i + ii][0] != base_states[i + ii][1] and (base_states[i + ii][0] != "-" or base_states[i + ii][1] != "-"):
                        # e.g. 2345 A AC,A -> only 2345 A AC

                        temp = 0
                        if base_states[i + ii][0] != "-":
                            temp = base_states[i + ii][0]
                        elif base_states[i + ii][1] != "-":
                            temp = base_states[i + ii][1]
                        else:
                            print("Error here. E#778902334")

                        variants = str(
                            i) + " \t " + str(ref[i - 1]) + " \t " + str(ref[i - 1]) + str(temp)

                    else:
                        print(
                            "This case is not ready yet. Error critical in variant output. #6546547643443")
                else:
                    variants = variants + str(xtilde[i + ii][0])
                if ii == this_gap_number - 1:
                    variant_list.append(variants)

        elif upd_ref[i + gap_counter] != "-":
            # Case: Deletion or SNP
            if xtilde[i + gap_counter] == 14:
                # Case: Complete Deletion / Deletion on both Strings
                #       e.g. 2345 CG C
                variants = str(
                    i) + " \t " + str(ref[i - 1]) + str(ref[i]) + " \t " + str(ref[i - 1])
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] == "-" or base_states[i + gap_counter][1] == "-":
                # Case: Deletion only on one String, base is conserved on other string or SNP.
                #       e.g. 2345 CG CA, C
                temp = 0
                if base_states[i + gap_counter][0] != "-":
                    temp = base_states[i + gap_counter][0]
                elif base_states[i + gap_counter][1] != "-":
                    temp = base_states[i + gap_counter][1]
                else:
                    print("Error. #78932784")

                variants = str(i) + " \t " + str(ref[i - 1]) + str(
                    ref[i]) + " \t " + str(ref[i - 1]) + temp + "," + str(ref[i - 1])
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] == base_states[i + gap_counter][1]:
                # Case: SNP is equal on both strings
                #       e.g. 2345 A C  Genotype: [C, C]
                variants = str(
                    i) + " \t " + str(ref[i]) + " \t " + str(base_states[i + gap_counter][0])
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] == upd_ref[i + gap_counter] or base_states[i + gap_counter][1] == upd_ref[i + gap_counter]:
                # Case: SNP only on one string
                #     e.g. 2345 A C    Genotype: [A, C]
                temp = 0
                if base_states[i + gap_counter][0] == upd_ref[i + gap_counter]:
                    temp = base_states[i + gap_counter][0]
                elif base_states[i + gap_counter][1] == upd_ref[i + gap_counter]:
                    temp = base_states[i + gap_counter][1]
                variants = str(i) + " \t " + str(ref[i]) + " \t " + temp
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] != upd_ref[i + gap_counter] and base_states[i + gap_counter][1] != upd_ref[i + gap_counter]:
                # Case: 2 different SNPs
                #       e.g. 2345 A C,G
                variants = str(i) + " \t " + str(ref[i]) + " \t " + base_states[i +
                                                                                gap_counter][0] + "," + base_states[i + gap_counter][1]
                variant_list.append(variants)

    # print(variant_list)
    return variant_list
