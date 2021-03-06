import pysam
from Bio import SeqIO


def get_ref_fasta(file_name):
    """
    reads a fasta-file and return the first sequence.
    Needs: a full file-name, e.g. : ref.fa
    :return: DNA-Sequence (as String) of a given fasta-file
    """
    record_dict = list(SeqIO.parse(file_name, "fasta"))
    return record_dict[0].seq


def get_sam(samfile):
    """
    reads a sam-file and returns a list with startposition, readnames,
    readsequence, [cigarstring as tuples], [queryqualities].
    return: All sorted reads from given sam-file.
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
    cuts out the hard and soft clipped entries from read sequence and/or cigar string
    and gets the insertion- and deletion positions to update reads and query qualities
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
    deletes all duplicate insertions from insertion list
    """
    insertions = sorted(insertions)
    unique_inserts = {}
    #  names = []
    for insert in insertions:
        insert = [(insert[0], insert[1]), insert[2]]
        if insert[0] in unique_inserts:
            unique_inserts[insert[0]].append(insert[1])
        else:
            unique_inserts[insert[0]] = [insert[1]]
    # for i in range(len(insertions) - 1):
    #     if insertions[i][0] != insertions[i + 1][0] or insertions[i][1] != insertions[i + 1][1]:
    #         unique_inserts.append(
    #             [insertions[i][0], insertions[i][1], names])
    #         # insertions[i][2].append(insertions[i + 1][2])
    #     else:
    #         names.append(insertions[i][2])
    return unique_inserts


def update_insertions(insertions):
    """
    updates startposition of insertions and returns new insertions
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
    updates startposition of reads
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
    insertion of gaps into reference sequence
    """
    for insert in insertions.keys():
        ref_seq = ref_seq[:insert[0]] + \
            insert[1] * '-' + ref_seq[insert[0]:]
    return ref_seq


def get_pileup(samfile, pileupposition):
    bases = []
    qualities = []
    mapping_qualities = []
    for read in samfile:

        if read[0] <= pileupposition and read[0] + len(read[2]) > pileupposition:
            bases.append(read[2][pileupposition - read[0]])
            qualities.append(read[5][pileupposition - read[0]])
            mapping_qualities.append(read[4])

    return bases, qualities, mapping_qualities


def main():
    # gat data
    # sam = get_sam('data/test_10X_Coverage/read_sort.sam')
    sam = get_sam('data/example.sam')
    # ref_seq = get_ref_fasta('data/test_10X_Coverage/ref.fa')
    ref_seq = get_ref_fasta('data/ref.fa')

    # get updated data
    newsam, insertions = get_cigar(sam)

    unique_inserts = del_duplicate_ins(insertions)
    upd_inserts = update_insertions(unique_inserts)

    upd_sam = update_startpos(newsam, upd_inserts)
    updated_sam = update_reads(upd_sam, upd_inserts)
    updated_refseq = update_ref(ref_seq, upd_inserts)

    # test
    for i in range(400):
        bases, _, _ = get_pileup(updated_sam, i)
        print(i, updated_refseq[i], bases)

    print(updated_refseq[3100:3400])


if __name__ == '__main__':
    main()
