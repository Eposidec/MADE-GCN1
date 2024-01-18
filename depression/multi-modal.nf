if (nextflow.version.matches(">=20.07.1")){
    nextflow.enable.dsl=2
}else{
    // Support lower version of nextflow
    nextflow.preview.dsl=2
}


projectDir = workflow.projectDir

params.path_test_fMRI = "/home/lining/xmn/model/SCZ/GAD/56_new/fMRI.csv"
params.path_test_sMRI = "/home/lining/xmn/model/SCZ/GAD/56_new/sMRI.csv"
params.path_test_DTI = "/home/lining/xmn/model/SCZ/GAD/56_new/DTI.csv"
params.judge = "y"
params.h = "depression test"


workflow {

    depression()
}


process exitCheck {
    output:
    val ' '
    if (file("${params.path_test_fMRI}").exist() & file("${params.path_test_sMRI}").exist() &(file("${params.path_test_DTI}").exist() || params.judge != "y")) {

        exit 1

    }

    """
    echo error
    """
}
process depression {


    script:
    if (params.judge == "y")
    {
    println "Predict with fMRI,sMRI,DTI"
    println "${params.path_test_fMRI}"
    println "${params.path_test_sMRI}"
    println "${params.path_test_DTI}"
    println params.judge

    }
    else {
    println "Predict with fMRI,sMRI"
    }

    """
    python ${projectDir}/main.py \
            --path_test_fMRI ${params.path_test_fMRI} \
            --path_test_sMRI ${params.path_test_sMRI} \
            --path_test_DTI ${params.path_test_DTI} \
            --judge ${params.judge}
    """
}