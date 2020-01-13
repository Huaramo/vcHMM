import math
from scipy.special import logsumexp
import pysam
import argparse
from Bio import SeqIO

import numpy as np


def get_ref_fasta(file_name):
    """
    Reads a fasta-file and return the first DNA-Sequence.
    Needs: a full file-name, e.g. : ref.fa 
    :return: DNA-Sequence (as String) of a given fasta-file.
    """
    record_dict = list(SeqIO.parse(file_name, "fasta"))
    return record_dict[0].seq


def get_sam(samfile):
    """
    Reads a sam-file and returns a list with startposition, readnames,
    readsequence, [cigarstring as tuples], [queryqualities] and mapquality.
    Needs: a full file-name, e.g. : ref.fa 
    :return: All sorted reads from given sam-file.
    """
    samfile = pysam.AlignmentFile(samfile, "rb")
    sam = []
    for read in samfile:
        sam.append([read.reference_start, read.query_name, read.query_sequence,
                    read.cigartuples, read.mapping_quality, read.query_qualities.tolist()])
        sam.sort()
    return sam


def get_cigar(sam):
    """
    Cuts out the hard and soft clipped entries from read sequence and/or cigar string
    and gets the insertion- and deletion positions to update reads and query qualities.
    Needs: sam-reads-variable from get_sam
    :return: newsam und insertions-list (locations and legth)
    """
    newsam = []
    insertions = []
    readnames = []

    for read in sam:
        soft_at_beginning = True
        hard_at_beginning = True
        same_read = True
        nr_insertions = 0
        gaps_before = 0
        pos = 0
        # read[3] is cigarstring (operation, length)
        if read[3] is None:
            continue
        else:
            for operation in read[3]:

                # soft and hard clipping only at beginning and end
                if operation[0] == 4:
                    # Soft clipped, delete sequence from read and from cigar string
                    if soft_at_beginning:
                        soft_at_beginning = False
                        read = [read[0] + operation[1], read[1],
                                read[2][operation[1]:], read[3][1:], read[4], read[5]]
                    else:
                        read = [read[0], read[1],
                                read[2][:-(operation[1])], read[3][:-1], read[4], read[5]]

                elif operation[0] == 5:
                    # Hard clipped, delete tuple from cigar string
                    if hard_at_beginning:
                        hard_at_beginning = False
                        read = [read[0], read[1], read[2],
                                read[3][1:], read[4], read[5]]
                    else:
                        read = [read[0], read[1], read[2],
                                read[3][:-1], read[4], read[5]]

                elif operation[0] == 1:
                    if read[1] not in readnames:
                        if same_read:
                            same_read = False
                            nr_insertions = operation[1]
                            insertions.append(
                                [read[0] + pos, operation[1], read[1]])
                        else:
                            insertions.append(
                                [read[0] + pos - nr_insertions, operation[1], read[1]])
                    else:
                        newname = read[1] + 'b'
                        read = [read[0], newname,
                                read[2], read[3], read[4], read[5]]
                        if same_read:
                            same_read = False
                            nr_insertions = operation[1]
                            insertions.append(
                                [read[0] + pos, operation[1], read[1]])
                        else:
                            insertions.append(
                                [read[0] + pos - nr_insertions, operation[1], read[1]])

                elif operation[0] == 2:
                    # Deletion: add deletions in readsequence
                    gaps_before = read[2][:pos].count('-')
                    updated_read = read[2][: pos + gaps_before] + \
                        operation[1] * '-' + \
                        read[2][pos + gaps_before:]
                    updated_qual = read[5][: pos + gaps_before] + \
                        operation[1] * ['-'] + \
                        read[5][pos + gaps_before:]
                    read = [read[0], read[1], updated_read,
                            read[3], read[4], updated_qual]
    #                deletions.append([read[1], pos, operation[1]])
                pos += operation[1]

        readnames.append(read[1])

        newsam.append(read)

    return newsam, insertions  # , deletions


def del_duplicate_ins(insertions):
    """
    Deletes all duplicate insertions from insertion list.
    e.g.
        [200 2, 200 2, 202 4] -> [200 2, 202 4] 
        #0: Insertions at Index 200 with len of 2
        #1: Insertions at Index 202 ...
    """
    insertions = sorted(insertions)
    unique_inserts = {}

    for insert in insertions:
        insert = [(insert[0], insert[1]), insert[2]]
        if insert[0] in unique_inserts:
            unique_inserts[insert[0]].append(insert[1])
        else:
            unique_inserts[insert[0]] = [insert[1]]

    return unique_inserts


def update_insertions(insertions):
    """
    Updates Startposition of insertions and returns new insertions.
    
    Checks for insertions before the respective insertions to modify 
    the start position of the respective insertion. 
    This step is required to align the insertions with the modified 
    reference genome.
    
    e.g. [200 2], 10 Insertions before -> [210 2]
    
    :return: newsam
    """
    temp = 0
    upd_inserts = {}
    for insert in insertions.keys():
        insert = [insert[0] + temp, insert[1], insertions[insert]]
        temp += insert[1]
        upd_inserts[(insert[0], insert[1])] = insert[2]
    return upd_inserts


def update_startpos(sam, insertions):
    """
    Updates startposition of reads.
    
    Checks for insertions before the read to modify the 
    start position of the read. 
    This step is required to align the reads with the modified 
    reference genome.
    """
    newsam = []
    for read in sam:
        for insert in insertions.keys():
            if read[0] > insert[0]:
                read = [read[0] + insert[1], read[1], read[2],
                        read[3], read[4], read[5]]

        newsam.append(read)

    return newsam


def update_reads(sam, insertions):
    """
    Gaps are inserted into reads and query quality that
    originate from insertions of other reads. This is necessary to 
    correctly align the reads with the modified genome reference.
    
    :return: newsam (with external Gaps)
    """
    newsam = []
    for read in sam:

        for insert in insertions.keys():
            gaps_before = 0
            # insert gaps into reads and into query quality
            if (read[1] not in insertions[insert]) and (insert[0] >= read[0]) and (insert[0] - read[0] <= len(read[2])):
                gaps_before = read[2][:insert[0] - read[0]].count('-')
                gapped_read = read[2][:insert[0] - read[0] + gaps_before] + \
                    insert[1] * '-' + \
                    read[2][insert[0] - read[0] + gaps_before:]
                changed_qual = read[5][:insert[0] - read[0] + gaps_before] + \
                    insert[1] * ['-'] + \
                    read[5][insert[0] - read[0] + gaps_before:]
                read = [read[0], read[1], gapped_read,
                        read[3], read[4], changed_qual]

        newsam.append(read)

    return newsam


def update_ref(ref_seq, insertions):
    """
    Insert gaps into reference sequence from read-cigar-strings.
    e.g.
        ACGTACGT -> ACGT--ACGT
    """
    for insert in insertions.keys():
        ref_seq = ref_seq[:insert[0]] + \
            insert[1] * '-' + ref_seq[insert[0]:]
    return ref_seq


def get_pileup(samfile, pileupposition):
    """
    Get all read bases, qualities and mapq for a given reference position. 
    Needs:  samfile(with all kind of modifications from before!), 
            pileupposition(Reference-Positions) 
    
    e.g.
        R[2] -> ["A", "A", "A", "C", "C", "C"], [22, 12, 23, 20, 18, 21],  [18, 19, 17, 23, 20, 19]
    
    :return: bases, qualities and mapping_qualities (mapq)
    """
    bases = []
    qualities = []
    mapping_qualities = []
    for read in samfile:

        if read[0] <= pileupposition and read[0] + len(read[2]) > pileupposition:
            bases.append(read[2][pileupposition - read[0]])
            qualities.append(read[5][pileupposition - read[0]])
            mapping_qualities.append(read[4])

    return bases, qualities, mapping_qualities


def create_row_transition_matrix(vector_of_pre_transition_matrix, hetrate):
    """
    Calculates a row of the transition Matrix, given a 
    "pre transition matrix" and a hetrate.
    Keep in Mind:
        - Pre Transition Matrix: only 4 hidden States, because 
        for predicting heterozygous polymorphism,
        one needs a more advanced Transition Matrix
        - States are 1-based, python-code is 0-based 
            -> transrow(30) = row_transition_matrix[29]

     :return:  A single row for the Transition Matrix
    """

    m = 30
    row_transition_matrix = [-1 for i in range(m)]
    
    # transrow(30) = tprobi(4) * hetrate/32;
    row_transition_matrix[29] = vector_of_pre_transition_matrix[3] * hetrate / 32

    # transrow(1) = tprobi(1) * (1-hetrate)*(1-transrow(30));
    row_transition_matrix[0] = vector_of_pre_transition_matrix[0] * \
        (1 - hetrate) * (1 - row_transition_matrix[29])

    # transrow(2: 4) = tprobi(2) * (1 - hetrate) / 3 * (1 - transrow(30));
    for i in range(1, 3 + 1):
        row_transition_matrix[i] = vector_of_pre_transition_matrix[1] * (1 - hetrate) / 3 * (
            1 - row_transition_matrix[29])

    # transrow(5: 7) = (tprobi(1) + tprobi(2) / 3) * hetrate / 4 * (1 - transrow(30));
    for i in range(4, 6 + 1):
        row_transition_matrix[i] = (vector_of_pre_transition_matrix[0] + vector_of_pre_transition_matrix[1] / 3) * \
            hetrate / 4 * (1 - row_transition_matrix[29])

    # transrow(8) = (tprobi(1) + tprobi(3)) * hetrate/4*(1-transrow(30));
    row_transition_matrix[7] = (vector_of_pre_transition_matrix[0] + vector_of_pre_transition_matrix[2]) * \
        hetrate / 4 * (1 - row_transition_matrix[29])

    # transrow([9:10,12]) = tprobi(2) * hetrate/6*(1-transrow(30));
    for i in ([8, 9, 11]):
        row_transition_matrix[i] = vector_of_pre_transition_matrix[1] * \
            hetrate / 6 * (1 - row_transition_matrix[29])

    # transrow([11,13,14]) = (tprobi(2)/3 + tprobi(3)) * hetrate/4*(1-transrow(30));
    for i in ([10, 12, 13]):
        row_transition_matrix[i] = ((vector_of_pre_transition_matrix[1] / 3 + vector_of_pre_transition_matrix[2]) *
                                    hetrate / 4 * (1 - row_transition_matrix[29]))

    # transrow(15) = tprobi(3) * (1 - hetrate) * (1 - transrow(30));
    row_transition_matrix[14] = vector_of_pre_transition_matrix[2] * \
        (1 - hetrate) * (1 - row_transition_matrix[29])

    # transrow(16:19) = tprobi(4) * (1-hetrate) / 4 * (1 - transrow(30));
    for i in range(15, 18 + 1):
        row_transition_matrix[i] = vector_of_pre_transition_matrix[3] * (1 - hetrate) / 4 * (1 -
                                                                                             row_transition_matrix[29])

    # transrow([20:22,24,25,27]) = tprobi(4) * hetrate/8*(1-transrow(30));
    for i in ([19, 20, 21, 23, 24, 26]):
        row_transition_matrix[i] = vector_of_pre_transition_matrix[3] * hetrate / 8 * (1 -
                                                                                       row_transition_matrix[29])

    # transrow([23,26,28,29]) = tprobi(4) * hetrate/16*(1-transrow(30));
    for i in ([22, 25, 27, 28]):
        row_transition_matrix[i] = vector_of_pre_transition_matrix[3] * hetrate / 16 * (1 -
                                                                                        row_transition_matrix[29])

    return row_transition_matrix


def create_transition_matrix(pre_transition_matrix, hetrate):
    """
    
    """
    
    # size of transition matrix: m
    m = 30
    # = [[-1 for i in range(m)] for j in range(m)]
    transition_matrix = [-1 for i in range(m)]

    ### This one: MATCH
    #  (1,:)= buildTrans(tprob(1,:), hetrate);
    transition_matrix[0] = create_row_transition_matrix(
        pre_transition_matrix[0], hetrate)

    ### This one: SNP
    # transitionmatrix(2,:)= buildTrans(tprob(2,:),hetrate);
    transition_matrix[1] = create_row_transition_matrix(
        pre_transition_matrix[1], hetrate)
    # transitionmatrix(3,:) = transitionmatrix(2,:);
    # transitionmatrix(4,:) = transitionmatrix(2,:);
    # transitionmatrix(5,:) = transitionmatrix(2,:);
    # transitionmatrix(6,:) = transitionmatrix(2,:);
    # transitionmatrix(7,:) = transitionmatrix(2,:);
    # transitionmatrix(9,:) = transitionmatrix(2,:);
    # transitionmatrix(10,:) = transitionmatrix(2,:);
    # transitionmatrix(12,:) = transitionmatrix(2,:);
    for i in ([2, 3, 4, 5, 6, 8, 9, 11]):
        transition_matrix[i] = transition_matrix[1]

    ### This one: Full-Delition
    # transitionmatrix(15,:) = buildTrans(tprob(3,:), hetrate);
    transition_matrix[14] = create_row_transition_matrix(
        pre_transition_matrix[2], hetrate)

    ### Part-Deletions: this are all Genotypes with ONE GAP (deletion). 
    #   order is NOT the same as the paper, but same as in Matlab
    # transitionmatrix(8,:) = (transitionmatrix(2,:)+transitionmatrix(15,:))/2;
    # transitionmatrix(11,:) = transitionmatrix(8,:);
    # transitionmatrix(13,:) = transitionmatrix(8,:);
    # transitionmatrix(14,:) = transitionmatrix(8,:);

    for i in ([7, 10, 12, 13]):
        transition_matrix[i] = [-1 for i in range(m)]
        for j in range(0, len(transition_matrix[1])):
            transition_matrix[i][j] = (
                transition_matrix[1][j] + transition_matrix[14][j]) / 2

    ### This are: INSERTIONs
    # transitionmatrix(16,:) = buildTrans(tprob(4,:),hetrate);
    # transitionmatrix(17,:) = transitionmatrix(16,:);
    # transitionmatrix(18,:) = transitionmatrix(16,:);
    # transitionmatrix(19,:) = transitionmatrix(16,:);
    # transitionmatrix(20,:) = transitionmatrix(16,:);
    # transitionmatrix(21,:) = transitionmatrix(16,:);
    # transitionmatrix(22,:) = transitionmatrix(16,:);
    # transitionmatrix(23,:) = transitionmatrix(16,:);
    # transitionmatrix(24,:) = transitionmatrix(16,:);
    # transitionmatrix(25,:) = transitionmatrix(16,:);
    # transitionmatrix(26,:) = transitionmatrix(16,:);
    # transitionmatrix(27,:) = transitionmatrix(16,:);
    # transitionmatrix(28,:) = transitionmatrix(16,:);
    # transitionmatrix(29,:) = transitionmatrix(16,:);
    transition_matrix[15] = create_row_transition_matrix(
        pre_transition_matrix[3], hetrate)
    for i in range(16, 29):
        transition_matrix[i] = transition_matrix[15]

    ### This one: Invalid State
    transition_matrix[29] = [1 / 30 for i in range(m)]

    return transition_matrix


def build_emissionmatrix(upd_sam, upd_reference):
    """
    Create the Emission Matrix.
    :param pile_up_read:
    :param pile_up_quality:
    :param updated_reference:
    :param mapq_list:
    :return: Emission Matrix
    """
    ### Creating Genotype-Vectors / Hidden-State-Vectors
    # This is a "translation" from the MATLAB-Code, from numbers to letters.
    vector_A = [["A", "A"], ["C", "C"], ["G", "G"], ["T", "T"], ["A", "C"], ["A", "G"], ["A", "T"], ["A", "-"],
                ["C", "G"], ["C", "T"], ["C", "-"], ["G", "T"], ["G", "-"], ["T", "-"], ["-", "-"]]
    vector_C = [["C", "C"], ["A", "A"], ["G", "G"], ["T", "T"], ["A", "C"], ["C", "G"], ["C", "T"], ["C", "-"],
                ["A", "G"], ["A", "T"], ["A", "-"], ["G", "T"], ["G", "-"], ["T", "-"], ["-", "-"]]
    vector_G = [["G", "G"], ["A", "A"], ["C", "C"], ["T", "T"], ["A", "G"], ["C", "G"], ["G", "T"], ["G", "-"],
                ["A", "C"], ["A", "T"], ["A", "-"], ["C", "T"], ["C", "-"], ["T", "-"], ["-", "-"]]
    vector_T = [["T", "T"], ["A", "A"], ["C", "C"], ["G", "G"], ["A", "T"], ["C", "T"], ["G", "T"], ["T", "-"],
                ["A", "C"], ["A", "G"], ["A", "-"], ["C", "G"], ["C", "-"], ["G", "-"], ["-", "-"]]
    #keep in mind: vector_Gap = vectot_A
    
    ematrix = []  # Length: updated_reference * 30


    # This loop is for The len of reference / Run over reference.
    # For every Reference-Base: creating emission prob. for 30 states(list)
    # 
    for i in range(len(upd_reference)):
        
        # get pileup of reads
        # get pileup of quality
        # get mapq
        pileup, pileup_qual, mapq_list = get_pileup(upd_sam, i)

        # skip loop, if len(read-pileup) is <5 or Reference-Base is a "N"
        # append -1 as indicator for this case
        if len(pileup) < 5 or upd_reference[i] == "N":
            ematrix.append(-1)
            continue

        ## Change quality score:
        # case: all values belong to gaps, problem: gaps do not have q-scores
        # quality-score -> mapq/4
        if all(elem == pileup_qual[0] for elem in pileup_qual) and [pileup_qual[p] == "-" for p in range(len(pileup_qual))]:
            for y in range(len(pileup_qual)):
                pileup_qual[y] = mapq_list[y] / 4
        
        ## Change quality score:
        # case: somegaps are given, problem: gaps do not have q-scores!
        # missing scores: means of other scores
        elif "-" in pileup_qual:
            tempt_counter = 0
            temp_val = 0
            for y in range(len(pileup_qual)):
                if not pileup_qual[y] == "-":
                    tempt_counter = tempt_counter + 1
                    temp_val = temp_val + pileup_qual[y]

            mean = temp_val / tempt_counter
            for y in range(len(pileup_qual)):
                if pileup_qual[y] == "-":
                    pileup_qual[y] = mean

        ## For Sub-Loop of genotypes: ii
        # Creating genotype list: 1 to 30 (Python: 0 to 29)
        # Keep in Mind: Genotype = VectorPart = State
        temp_list = []
        temp_value = 0

        # case: If Reference-Base at i is a Gap
        if upd_reference[i] == "-":
            vector = vector_A  # Keep in mind, Vector A == Vector for gaps!

            # In case Ref[i] == "-":  emission prob. for states 1 to 15: NaN
            for ii in range(15):
                temp_list.append("NaN")

            # list values else: 3 if-cases fro every element in pile-up
            for ii in range(15, 30):

                ## Filter: 
                # filter-case: if Vector at R[i] == Gap, Genotype == Gap and >80% of reads are gaps:
                gap_counter = 0
                for z in range(len(pileup)):
                    if pileup[z] == "-":
                        gap_counter = gap_counter + 1
                if vector[ii - 15] == ["-", "-"] and gap_counter >= len(pileup) * 0.8:
                    temp_list.append(0)
                    continue
                    
                ## Filter
                # NaN-Checking: in vector part ii is no match with any element from pile-up-list
                nan_controll = 0
                for sub in range(len(pileup)):
                    if vector[ii - 15][0] == pileup[sub] or vector[ii - 15][1] == pileup[sub]:
                        nan_controll = 1

                if nan_controll == 0:
                    temp_list.append("NaN")
                    continue

                # Loop over Pile-Up
                ## 3 possible cases: 
                temp_value = 0
                for subi in range(len(pileup)):

                    # Case1: PileUp[subi] is in both Elements of Vector Part
                    if vector[ii - 15][0] == pileup[subi] and vector[ii - 15][1] == pileup[subi]:
                        #   log10(1 - 10 ^ (-qscore[subi] / 10))
                        temp_pow = np.power(10, (-pileup_qual[subi] / 10))
                        temp = np.log10(1 - temp_pow)
                        temp_value = temp_value + temp
                    
                    # Case2: PileUp[subi] is not in both Elements of Vector Part
                    elif pileup[subi] != vector[ii - 15][0] and pileup[subi] != vector[ii - 15][1]:
                        #   -qscore[subi] / 10 +log10(0.25)
                        temp = (-pileup_qual[subi] / 10 + np.log10(0.25))
                        temp_value = temp_value + temp

                    # Case3: PileUp[subi] is in on Element of Vector Part
                    else:
                        #   log10(0.5*(1-10^(-qscore[subi]/10)) + 0.125*10^(-qsccore[subi] / 10))
                        temp_pow = np.power(10, (-pileup_qual[subi] / 10))
                        temp = 0.5 * (1 - temp_pow) + 0.125 * temp_pow
                        temp_log = np.log10(temp)
                        temp_value = temp_value + temp_log

                temp_list.append(temp_value)
            ematrix.append(temp_list)
            temp_list = []

        # Case: If Reference-Base at i is not a Gap
        else:
            # Get Vector:
            # Keep in Mind: One does not need THIS in case of
            # a gap, because at gaps, every Vector is the same
            if upd_reference[i] == "A":
                vector = vector_A
            elif upd_reference[i] == "C":
                vector = vector_C
            elif upd_reference[i] == "G":
                vector = vector_G
            elif upd_reference[i] == "T":
                vector = vector_T
            else:
                print("Critical Error at creating emission-matrix! #2349862")

            # Sub-Loop of genotypes: ii
            for ii in range(15):
                temp_value = 0

                ## Filter: 
                # skip loop, if len(read-pileup) is <5 or Reference-Base is a "N"
                # append -1 as indicator for this case
                gap_counter = 0
                for z in range(len(pileup)):
                    if pileup[z] == "-":
                        gap_counter = gap_counter + 1
                if vector[ii] == ["-", "-"] and gap_counter >= len(pileup) * 0.8:
                    temp_list.append(0)
                    continue
                    
                ## Filter
                # NaN-Checking: in vector part ii is no match with any element from pile-up-list
                nan_controll = 0
                for sub in range(len(pileup)):
                    if vector[ii][0] == pileup[sub] or vector[ii][1] == pileup[sub]:
                        nan_controll = 1

                if nan_controll == 0:
                    temp_list.append("NaN")
                    continue

                # Loop over Pile-Up
                for subi in range(len(pileup)):

                    # Case1: PileUp[subi] is in both Elements of Vector Part
                    if vector[ii - 15][0] == pileup[subi] and vector[ii - 15][1] == pileup[subi]:
                        #   log10(1 - 10 ^ (-qscore[subi] / 10))
                        temp_pow = np.power(10, (-pileup_qual[subi] / 10))
                        temp = np.log10(1 - temp_pow)
                        temp_value = temp_value + temp

                    # Case2: PileUp[subi] is not in both Elements of Vector Part
                    elif pileup[subi] != vector[ii - 15][0] and pileup[subi] != vector[ii - 15][1]:
                        #   -qscore[subi] / 10 +log10(0.25)
                        temp = (-pileup_qual[subi] / 10 + np.log10(0.25))
                        temp_value = temp_value + temp

                    # Case3: PileUp[subi] is in on Element of Vector Part
                    else:
                        #   log10(0.5*(1-10^(-qscore[subi]/10)) + 0.125*10^(-qsccore[subi] / 10))
                        temp_pow = np.power(10, (-pileup_qual[subi] / 10))
                        temp = 0.5 * (1 - temp_pow) + 0.125 * temp_pow
                        temp_log = np.log10(temp)
                        temp_value = temp_value + temp_log

                temp_list.append(temp_value)

            # In case: Ref[i] != "-": emission prob. for states 15-30: nan
            for ii in range(15, 30):
                temp_list.append("NaN")
            ematrix.append(temp_list)
            temp_list = []

    return ematrix


def viterbi(emission_matrix, transmission_matrix):
    """
    Does Vitervi Hidden Markov for a given transition and emission matrix.
    2 Parts.
    -Viterbi
    -Xtilde
    
    :param emission_matrix:
    :param transmission_matrix:
    :return: xtilde (path of most likely Hidden States)
    """

    ## Creating variables:
    # initialprob: first row of trans-matrix
    initialprob = transmission_matrix[0]
    delta = []
    
    # Change NaN to -inf (np.NINF)
    for i in range(len(emission_matrix)):
        if emission_matrix[i] == -1:
            continue
        for j in range(len(emission_matrix[i])):
            if emission_matrix[i][j] == "NaN":
                emission_matrix[i][j] = np.NINF

    
    ####################
    #### Run Viterbi ###
    ####################
    
    # Important:  if -1 -> skip this part and.
    #             if skip because of -1: use initialprob for first next element != -1 in Ri
    for i in range(len(emission_matrix)):
        
        ## Case: -1 / skip
        # append -1 as indicator for -1
        # e.g.
        #   x x x -1  x x x x x x ...
        #   z z z  s  y y y y y ...
        #   z z z  k  y y y y ...
        #   z z z  i  y y y y ...
        #   z z z  p  y y y y ...
        #
        # Why: Every -1 cases cut the matrix. Each part must be calculated separately.
        if emission_matrix[i] == -1:
            delta.append(-1)
            continue

        ## Case: Initialization
        #   R[i] == 0 or (R[i] != -1 and R[i-1] == -1)
        #   This starts a separately calculation 
        if i == 0 or (emission_matrix[i] != -1 and emission_matrix[i - 1] == -1):
            temp_list = []
            temp = 0
            sum = 0
            for ii in range(len(emission_matrix[i])):
                temp = initialprob[ii] * np.exp(emission_matrix[i][ii])
                temp_list.append(temp)
                sum = sum + temp

            for ii in range(len(emission_matrix[i])):
                temp_list[ii] = temp_list[ii] / sum
            delta.append(temp_list)

        # Case: Consecutive sequence
        #   -e.g.  ACGTACGT, without -1
        else:
            delta_matrix = []
            # Keep in mind: delta_matrix != delta
            # delta_matrix :         a temp. Matrix for calculation
            # true_delta_matrix :    a temp. Matrix for calculation
            # delta:                 saves solutions of needed calculations
            
            true_delta_matrix = []
            true_temp = 0
            true_temp_list = []
            for y in range(30):
                delta_matrix.append(delta[i - 1])

            # Matrix Calculation:
            #   - Delta-Matrix .* Transition-Matrix
            for y in range(30):
                for z in range(30):
                    if delta_matrix[y][z] != "NaN":
                        true_temp = float(
                            transmission_matrix[y][z]) * float(delta_matrix[y][z])
                        true_temp_list.append(true_temp)

                    else:
                        true_temp = "NaN"
                        true_temp_list.append(true_temp)
                true_delta_matrix.append(true_temp_list)
                true_temp_list = []

            # Get Max-Values from true_delta_matrix-rows
            # e.g.
            # [1,2,3,4] -> [4,
            # [2,3,4,5] ->  5,
            # [4,3,2,1] ->  4,
            # [5,5,5,7] ->  7]
            # Input Matrix, Output List
            temp_max = np.NINF
            max_list = []
            for y in range(30):
                temp_max = np.max(true_delta_matrix[y])
                max_list.append(temp_max)
                temp_max = np.NINF

            # Get Log-Values from Max-Values(List)
            for y in range(30):
                if max_list[y] != "NaN":
                    # print(y)
                    # print(max_list[y])
                    max_list[y] = np.log(float(max_list[y]))
                else:
                    max_list[y] = np.NINF

            # Every value(in list) plus emission prob.
            emmi_list = []
            for y in range(30):
                if "nan" != max_list[y]:  # nan to NaN
                    emmi_list.append(
                        float(max_list[y]) + float(emission_matrix[i][y]))
            max_list = []

            # Logsumexp:
            # First exp, than sum of list and log
            # get a single value
            den = logsumexp(emmi_list)

            # Exp of every value(list) and sub. of logsumexp
            temp_list = []
            for y in range(len(emmi_list)):
                temp_list.append(np.exp(emmi_list[y] - den))

            delta.append(temp_list)

    
    ####################
    #### Get xtilde  ###
    ####################
    # Get Path of Hidden Satets
    # Get most likely Hidden States as a List
    
    xtilde = []
    # reverse, bacuse xtilde is done backwards
    delta.reverse()

    for i in (range(len(delta))):
        # Case: Skip
        #   x x x -1  x x x x x x ...
        #   z z z  s  y y y y y ...
        #   z z z  k  y y y y ...
        #   z z z  i  y y y y ...
        #   z z z  p  y y y y ...
        if delta[i] == -1:
            xtilde.append(-1)
            continue
            
        # Case: Initialization of new Sub-Part
        if (i == 0 and delta[i] != -1) or (delta[i] != -1 and delta[i + 1] == -1):
            temp = delta[i].index(np.max(delta[i]))
            xtilde.append(temp)

        else:
            trans_row = transmission_matrix[xtilde[i - 1]]
            temp_list = []
            for j in range(len(trans_row)):
                temp = 0
                temp = float(delta[i][j]) * float(trans_row[j])
                temp_list.append(temp)
            xtilde.append(temp_list.index(np.max(temp_list)))
            temp_list = []

    xtilde.reverse()
    print("Viterbi is done.")
    return xtilde


def find_base_state(xtilde, upd_ref):
    """
    Finds the most likely genotypes / Base State at every position of updated reference.
    
    e.g. at R[i] Base is G and hidden state(from xtilde) is 1: -> Base State is [G, G]
    
    :param xtilde:  Hidden State of Genome Reference
    :param upd_ref: Genome Reference with Gaps
    :return: base_states
    """
    base_state = []

    ### Creating Genotype-Vectors / Hidden-State-Vectors
    vector_A = [["A", "A"], ["C", "C"], ["G", "G"], ["T", "T"], ["A", "C"], ["A", "G"], ["A", "T"], ["A", "-"],
                ["C", "G"], ["C", "T"], ["C", "-"], ["G", "T"], ["G", "-"], ["T", "-"], ["-", "-"]]
    vector_C = [["C", "C"], ["A", "A"], ["G", "G"], ["T", "T"], ["A", "C"], ["C", "G"], ["C", "T"], ["C", "-"],
                ["A", "G"], ["A", "T"], ["A", "-"], ["G", "T"], ["G", "-"], ["T", "-"], ["-", "-"]]
    vector_G = [["G", "G"], ["A", "A"], ["C", "C"], ["T", "T"], ["A", "G"], ["C", "G"], ["G", "T"], ["G", "-"],
                ["A", "C"], ["A", "T"], ["A", "-"], ["C", "T"], ["C", "-"], ["T", "-"], ["-", "-"]]
    vector_T = [["T", "T"], ["A", "A"], ["C", "C"], ["G", "G"], ["A", "T"], ["C", "T"], ["G", "T"], ["T", "-"],
                ["A", "C"], ["A", "G"], ["A", "-"], ["C", "G"], ["C", "-"], ["G", "-"], ["-", "-"]]

    #Keep in Mind:  Vector for Base A = Vector for Base "-"
    vector_A_ex = vector_A
    vector_A_ex.extend(vector_A)

    vector_C_ex = vector_C
    vector_C_ex.extend(vector_A)

    vector_G_ex = vector_G
    vector_G_ex.extend(vector_A)

    vector_T_ex = vector_T
    vector_T_ex.extend(vector_A)

    # Loop over updated reference:
    for i in range(len(upd_ref)):
        
        # Case: xtilde(i) == -1: 
        #   skip this, base = -1
        if xtilde[i] == -1:
            base_state.append(-1)

        else:
            # Get Base at Ri:
            if upd_ref[i] == "A":
                base_state.append(vector_A_ex[xtilde[i]])

            elif upd_ref[i] == "C":
                base_state.append(vector_C_ex[xtilde[i]])

            elif upd_ref[i] == "G":
                base_state.append(vector_G_ex[xtilde[i]])

            elif upd_ref[i] == "T":
                base_state.append(vector_T_ex[xtilde[i]])

            elif upd_ref[i] == "N":
                base_state.append(upd_ref[i])
                print("Error. #9872536")
                # If this Error: Ns are forbidden.
                # Change logic request for selection.

            elif upd_ref[i] == "-":
                base_state.append(vector_A_ex[xtilde[i]])

            else:
                print("Critical Error. Unknown Base at Position ",
                      i, " in updated Reference! #666987")
                base_state.append(upd_ref[i])

    print("States are done.")
    return base_state


def create_variant_calling_output(ref, upd_ref, base_states, xtilde):

    variants = ""
    variant_list = []

    # For Difference between reference and updated reference
    gap_counter = 0

    for i in range(len(ref)):
        if xtilde[i + gap_counter] == 0 or xtilde[i + gap_counter] == 29 or xtilde[i + gap_counter] == -1:
            # Case: Hidden State: 1, 30 and -1
            #       1:  No Mutation
            #       30: Not valid state
            #       -1: not Data
            if upd_ref[i + gap_counter] == "-":
                gap_counter = gap_counter + 1
            continue

        elif upd_ref[i + gap_counter] == "-":
            ### Case: Gaps Insertions in updated reference
            #       Hidden States: 16 - 29
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
                ### Case: multiple Insertions in a row
                if ii == 0:
                    if base_states[i + ii + gap_counter][0] == base_states[i + ii + gap_counter - this_gap_number][1]:
                        # e.g. 2345 A AC

                        variants = str(
                            i) + "\t" + str(ref[i - 1]) + "\t" + str(ref[i - 1]) + str(base_states[i + ii  + gap_counter - this_gap_number][0])

                    elif base_states[i + ii  + gap_counter - this_gap_number][0] != base_states[i + ii  + gap_counter - this_gap_number][1] and (base_states[i + ii  + gap_counter - this_gap_number][0] != "-" and base_states[i + ii  + gap_counter - this_gap_number][1] != "-"):
                        # e.g. 2345 A AC,AG

                        variants = str(i) + "\t" + str(ref[i - 1]) + "\t" + str(ref[i - 1]) + str(
                            base_states[i + ii  + gap_counter - this_gap_number][0]) + "," + str(ref[i - 1]) + str(base_states[i + ii  + gap_counter - this_gap_number][1])

                    elif base_states[i + ii  + gap_counter - this_gap_number][0] != base_states[i + ii  + gap_counter - this_gap_number][1] and (base_states[i + ii  + gap_counter - this_gap_number][0] != "-" or base_states[i + ii  + gap_counter - this_gap_number][1] != "-"):
                        # e.g. 2345 A AC,A -> only 2345 A AC

                        temp = ""
                        if base_states[i + ii  + gap_counter - this_gap_number][0] != "-":
                            temp = str(base_states[i + ii  + gap_counter - this_gap_number][0])
                        elif base_states[i + ii  + gap_counter - this_gap_number][1] != "-":
                            temp = str(base_states[i + ii  + gap_counter - this_gap_number][1])
                        else:
                            print("Error here. E#778902334")

                        variants = str(
                            i) + "\t" + str(ref[i - 1]) + "\t" + str(ref[i - 1]) + str(temp)

                    else:
                        print(
                            "Error critical in variant output. #6546547643443")
                else:
                    ### Case: multiple Insertions in a row: e.g. 2345 G GTTTTTT
                    variants = str(variants) + str(base_states[i + ii  + gap_counter - this_gap_number][0])
                if ii == this_gap_number - 1:
                    variant_list.append(variants)

        elif upd_ref[i + gap_counter] != "-":
            ### Case: Deletion or SNP
            if xtilde[i + gap_counter] == 14:
                ### Case: Complete Deletion / Deletion on both Strings
                #       e.g. 2345 CG C
                variants = str(
                    i) + "\t" + str(ref[i - 1]) + str(ref[i]) + "\t" + str(ref[i - 1])
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] == "-" or base_states[i + gap_counter][1] == "-":
                ### Case: Deletion only on one String, base is conserved on other string or SNP.
                #       e.g. 2345 CG CA, C
                temp = 0
                if base_states[i + gap_counter][0] != "-":
                    temp = str(base_states[i + gap_counter][0])
                elif base_states[i + gap_counter][1] != "-":
                    temp = str(base_states[i + gap_counter][1])
                else:
                    print("Error. #78932784")

                variants = str(i) + "\t" + str(ref[i - 1]) + str(
                    ref[i]) + "\t" + str(ref[i - 1]) + temp + "," + str(ref[i - 1])
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] == base_states[i + gap_counter][1]:
                ### Case: SNP is equal on both strings
                #       e.g. 2345 A C  Genotype: [C, C]
                variants = str(
                    i) + "\t" + str(ref[i]) + "\t" + str(base_states[i + gap_counter][0])
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] == upd_ref[i + gap_counter] or base_states[i + gap_counter][1] == upd_ref[i + gap_counter]:
                ### Case: SNP only on one string
                #     e.g. 2345 A C    Genotype: [A, C]
                temp = 0
                if base_states[i + gap_counter][0] != upd_ref[i + gap_counter]:
                    temp = str(base_states[i + gap_counter][0])
                elif base_states[i + gap_counter][1] != upd_ref[i + gap_counter]:
                    temp = str(base_states[i + gap_counter][1])
                variants = str(i) + "\t" + str(ref[i]) + "\t" + temp
                variant_list.append(variants)

            elif base_states[i + gap_counter][0] != upd_ref[i + gap_counter] and base_states[i + gap_counter][1] != upd_ref[i + gap_counter]:
                ### Case: 2 different SNPs
                #       e.g. 2345 A C,G
                variants = str(i) + "\t" + str(ref[i]) + "\t" + base_states[i +
                                                                                gap_counter][0] + "," + base_states[i + gap_counter][1]
                variant_list.append(variants)
                
    return variant_list


def create_output_file(values, file):
    """
    Creates a VCF-File.
    Name is for sim. Data, change it for other Data.
    """
    # Add name-column to list
    new_values = []
    for element in values:
        print(element)
        temp = "simref\t" + element
        new_values.append(temp)

    # Add id-column
    new_values2 = []
    id_column_value = "\t.\t"
    needle = "\t"
    for i in range(len(new_values)):
        start = new_values[i].find(needle)
        n = 2
        while start >= 0 and n > 1:
            start = new_values[i].find(needle, start + len(needle))
            n -= 1
        temp = new_values[i][0:start] + id_column_value + \
            new_values[i][start + 1:len(new_values[i])]
        new_values2.append(temp)

    # Add Headlines and infos
    head_list = []
    meta_info = "##fileformat=VCFv4.0"
    head_list.append(meta_info)

    marker_info = "#CHROM\tPOS\tID\tREF\tALT"
    head_list.append(marker_info)

    head_list.extend(new_values2)

    # Create file
    with open(file, 'w') as output:
        for element in head_list:
            output.write(str(element) + '\n')


def parser():
    """
    Allows to use the tool from the command line.
    """
    parser = argparse.ArgumentParser(
        description='Calculating Variants in fasta file')
    parser.add_argument('-i', '--input', type=str,
                        help='Input reference file', required=True)
    parser.add_argument('-r', '--reads', type=str,
                        help='Input sam read file', required=True)
    parser.add_argument('-o', '--output', type=str,
                        help='Output vcf file', required=True)

    args = parser.parse_args()

    return args


def main():

    #### Create Variables:
    ## T-Matrix:
    # This one is pre-transition-matrix for simulated data:
    # header:                          MATCH, SNP, Deletion,  Insertion
    pre_transition_matrix_simulated = [[0.988, 0.008, 0.002, 0.002],
                                       [0.53, 0.45, 0.01, 0.01],
                                       [0.70, 0.15, 0.15, 0.0],
                                       [0.70, 0.15, 0.0, 0.15]]

    # This one is pre-transitions-matrix for real data
    # header:                       MATCH,      SNP,        Deletion,     Insertion
    pre_transition_matrix_real =  [[0.9838043, 0.01474720, 0.0006085089, 0.0008400445],
                                   [0.9499207, 0.04640025,
                                       0.0014855172, 0.0021934910],
                                   [0.2879631, 0.01089283,
                                       0.6994015911, 0.0017424552],
                                   [0.4163771, 0.01984721, 0.0040161923, 0.5597594535]]

    ## Heterozygous Rate
    # For simulated data:
    hetrate_simulated = 0.01
    # For real data
    hetrate_real = 0.001

    #### Get Data
    args = parser()
    sam = get_sam(args.reads)
    # sam = get_sam('data/test_10X_Coverage/read_sort.sam')
    ref_seq = get_ref_fasta(args.input)
    # ref_seq = get_ref_fasta('data/test_10X_Coverage/ref.fa')

    #### Get Updated Data
    newsam, insertions = get_cigar(sam)
    unique_inserts = del_duplicate_ins(insertions)
    upd_inserts = update_insertions(unique_inserts)
    upd_sam = update_startpos(newsam, upd_inserts)
    updated_sam = update_reads(upd_sam, upd_inserts)
    updated_refseq = update_ref(ref_seq, upd_inserts)


    #### Viterbi
    trans_matrix = create_transition_matrix(
        pre_transition_matrix_simulated, hetrate_simulated)
    emission_matrix = build_emissionmatrix(updated_sam, updated_refseq)
    xtilde = viterbi(emission_matrix, trans_matrix)
    hidden_states = find_base_state(xtilde, updated_refseq)

    #### Varient Output
    output = create_variant_calling_output(
        ref_seq, updated_refseq, hidden_states, xtilde)
    create_output_file(output, args.output)


if __name__ == '__main__':
    main()
